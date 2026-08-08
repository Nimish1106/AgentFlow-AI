"""Workflow execution runner: run the graph and persist what it produced.

This is the boundary the graph itself is forbidden to cross. Nodes never touch
the database (SRS §16.1) - they return state updates. The runner reads the final
state and writes the persistent consequences:

- ``workflow_runs``        - status transitions, current node, completion time
- ``agent_execution_logs`` - one row per agent that ran (SRS §18.6)
- ``audit_logs``           - workflow lifecycle + resolved conflicts (SRS §16.10)
- ``support_tickets``      - status and the customer-facing resolution

A run ends in one of three shapes:

- ``completed``        - the Dispatcher delivered a response
- ``waiting_for_hitl`` - the graph hit the HITL interrupt and is parked
- ``failed``           - a non-recoverable failure, or the runner itself raised
"""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.graph.nodes.aggregator import CONTEXT_KEY as AGGREGATION_KEY
from app.graph.nodes.risk_engine import CONTEXT_KEY as RISK_KEY
from app.graph.state import build_initial_state
from app.models import AgentExecutionLog, AuditLog, SupportTicket, WorkflowRun
from app.models.enums import SubscriptionPlan, TicketStatus, WorkflowStatus
from app.services.exceptions import WorkflowNotFoundError

logger = logging.getLogger(__name__)

AUDIT_ACTOR = "workflow-dispatcher"

#: Graph interrupt marker in the result of ``ainvoke``.
_INTERRUPT_KEY = "__interrupt__"


def extract_risk_assessment(result: Dict) -> Optional[Dict]:
    """Project the Risk Engine's assessment onto its persisted shape (SRS §39).

    The graph names the level ``risk_level`` and the score ``risk_score``; the
    stored record uses ``level``/``score``. Persisting it structurally is what
    lets the HITL review UI show a reviewer real fields instead of re-deriving
    the decision from prose.

    Returns None when the Risk Engine never ran (a workflow that failed earlier),
    so "no assessment" stays distinguishable from "assessed as no risk".
    """
    assessment = (result.get("shared_context") or {}).get(RISK_KEY)
    if not isinstance(assessment, dict) or not assessment:
        return None
    return {
        "score": assessment.get("risk_score", result.get("risk_score")),
        "level": assessment.get("risk_level"),
        "requires_hitl": bool(assessment.get("requires_hitl", False)),
        "reasons": list(assessment.get("reasons") or []),
    }


def _resumed_prefix_length(
    persisted: List[str], incoming: List[str]
) -> int:
    """How many leading ``incoming`` entries are already on disk.

    A resumed workflow replays its checkpointed trace, so the entries it returns
    overlap the rows already written. The overlap is the longest suffix of
    ``persisted`` that is also a prefix of ``incoming``: matching against the
    *suffix* is what makes this correct when rows from an earlier, unrelated
    attempt sit in front of the current one.

    Returns 0 when nothing lines up, which is the safe answer - the whole trace
    is appended as a fresh attempt rather than silently dropping nodes. Counting
    rows instead of matching them would do exactly that: one stray row would
    shift the offset and skip a real node.
    """
    if not persisted or not incoming:
        return 0
    for length in range(min(len(persisted), len(incoming)), 0, -1):
        if persisted[-length:] == incoming[:length]:
            return length
    return 0


class WorkflowRunner:
    """Runs one workflow (or resumes one) and persists the outcome.

    Args:
        graph: The compiled LangGraph workflow.
        session_factory: Async session factory for the persistence writes.
    """

    def __init__(
        self,
        graph: Any,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._graph = graph
        self._session_factory = session_factory

    async def run(self, workflow_id: uuid.UUID) -> Dict:
        """Execute a new workflow from its initial state."""
        state = await self._build_initial_state(workflow_id)
        return await self._execute(workflow_id, state)

    async def resume(self, workflow_id: uuid.UUID, decision: Dict) -> Dict:
        """Resume a workflow parked at the HITL interrupt (SRS §38).

        The reviewer's decision becomes the ``interrupt()`` return value inside
        the HITL node.
        """
        await self._audit(
            workflow_id,
            {"event": "workflow_resumed", "approved": decision.get("approved")},
        )
        return await self._execute(workflow_id, Command(resume=decision))

    async def _execute(self, workflow_id: uuid.UUID, graph_input: Any) -> Dict:
        """Invoke the graph and persist whatever state came back."""
        metadata: Dict[str, Any] = {"workflow_id": str(workflow_id)}
        tags: List[str] = ["agentflow"]
        run_name = f"Workflow-{workflow_id}"

        if isinstance(graph_input, dict):
            if graph_input.get("ticket_id"):
                metadata["ticket_id"] = str(graph_input["ticket_id"])
            if graph_input.get("customer_id"):
                metadata["customer_id"] = str(graph_input["customer_id"])
            if graph_input.get("customer_tier"):
                tier = str(graph_input["customer_tier"])
                metadata["customer_tier"] = tier
                tags.append(f"tier:{tier}")
            if graph_input.get("ticket_priority"):
                metadata["ticket_priority"] = str(graph_input["ticket_priority"])
        elif isinstance(graph_input, Command) and graph_input.resume:
            resume_data = graph_input.resume
            if isinstance(resume_data, dict):
                metadata["hitl_approved"] = bool(resume_data.get("approved"))
            run_name = f"Workflow-Resume-{workflow_id}"
            tags.append("hitl-resume")

        config = {
            "configurable": {"thread_id": str(workflow_id)},
            "metadata": metadata,
            "tags": tags,
            "run_name": run_name,
        }
        await self._mark_running(workflow_id)

        try:
            result = await self._graph.ainvoke(graph_input, config=config)
        except Exception as exc:  # noqa: BLE001 - a crash must still be recorded
            logger.exception("workflow_id=%s graph execution failed", workflow_id)
            await self._mark_failed(workflow_id, f"graph execution failed: {exc}")
            raise

        await self._persist_outcome(workflow_id, result)
        return result

    async def _build_initial_state(self, workflow_id: uuid.UUID):
        """Load the ticket and customer context into a fresh GraphState."""
        async with self._session_factory() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
            if workflow is None:
                raise WorkflowNotFoundError(str(workflow_id))

            ticket = await session.get(SupportTicket, workflow.ticket_id)
            if ticket is None:
                raise WorkflowNotFoundError(
                    f"workflow {workflow_id} references missing ticket "
                    f"{workflow.ticket_id}"
                )
            tier = await self._customer_tier(session, ticket.customer_id)

        return build_initial_state(
            workflow_id=str(workflow_id),
            ticket_id=str(ticket.id),
            customer_id=str(ticket.customer_id),
            issue_text=f"{ticket.title}\n\n{ticket.description}",
            customer_tier=tier,
            ticket_priority=ticket.priority.value,
        )

    async def _customer_tier(
        self, session: AsyncSession, customer_id: uuid.UUID
    ) -> str:
        """Return the customer's subscription plan as their tier."""
        from app.models import Subscription

        plan: Optional[SubscriptionPlan] = await session.scalar(
            select(Subscription.plan)
            .where(Subscription.user_id == customer_id)
            .limit(1)
        )
        return plan.value if plan is not None else "basic"

    async def _persist_outcome(self, workflow_id: uuid.UUID, result: Dict) -> None:
        """Write the workflow's persistent consequences (SRS §13 step 15)."""
        if result.get(_INTERRUPT_KEY):
            await self._mark_waiting_for_hitl(workflow_id, result)
            return

        status = (
            WorkflowStatus.COMPLETED
            if result.get("workflow_status") == "completed"
            else WorkflowStatus.FAILED
        )

        async with self._session_factory() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
            if workflow is None:
                logger.warning(
                    "workflow_id=%s vanished before persistence", workflow_id
                )
                return

            workflow.workflow_status = status
            workflow.current_node = result.get("current_node")
            # DB-side now() keeps every timestamp on one clock.
            workflow.completed_at = func.now()

            assessment = extract_risk_assessment(result)
            if assessment is not None:
                workflow.risk_assessment = assessment

            await self._persist_trace(session, workflow_id, result)

            ticket = await session.get(SupportTicket, workflow.ticket_id)
            if ticket is not None and status is WorkflowStatus.COMPLETED:
                ticket.status = TicketStatus.RESOLVED
                ticket.resolution = result.get("final_response")

            session.add(
                AuditLog(
                    workflow_id=workflow_id,
                    action=json.dumps(
                        {
                            "event": "workflow_finished",
                            "workflow_status": status.value,
                            "approval_status": result.get("approval_status"),
                            "risk_score": result.get("risk_score"),
                            "errors": result.get("errors", []),
                        }
                    ),
                    performed_by=AUDIT_ACTOR,
                )
            )

            # SRS §40: a resolved conflict is recorded in the audit log.
            conflicts = (
                (result.get("shared_context") or {})
                .get(AGGREGATION_KEY, {})
                .get("conflicts")
                or []
            )
            for conflict in conflicts:
                session.add(
                    AuditLog(
                        workflow_id=workflow_id,
                        action=json.dumps(
                            {"event": "conflict_resolved", "detail": conflict}
                        ),
                        performed_by=AUDIT_ACTOR,
                    )
                )

            await session.commit()

        logger.info(
            "workflow_id=%s finished status=%s risk_score=%s",
            workflow_id,
            status.value,
            result.get("risk_score"),
        )

    async def _persist_trace(
        self, session: AsyncSession, workflow_id: uuid.UUID, result: Dict
    ) -> None:
        """Append new execution-trace rows to ``agent_execution_logs`` (SRS §18.6).

        ``node_executions`` is checkpointed GraphState, so a resumed run returns
        the *whole* trace - the nodes from before the HITL pause plus the ones
        that ran after it. Only the un-persisted tail is written.

        Execution history is append-only: rows already written are never deleted
        or rewritten, so every attempt survives a resume or a re-run. The tail is
        found by matching node names against the rows already on disk (see
        ``_resumed_prefix_length``), and new rows continue the existing sequence,
        which keeps a resumed trace reading continuously in order.

        Falls back to ``agent_results`` for a run whose state predates the trace
        channel (an in-flight workflow resumed across this deployment), so the
        dashboard still shows which agents ran.
        """
        persisted = list(
            await session.scalars(
                select(AgentExecutionLog.agent_name)
                .where(AgentExecutionLog.workflow_id == workflow_id)
                .order_by(AgentExecutionLog.sequence)
            )
        )
        next_sequence = int(
            await session.scalar(
                select(func.max(AgentExecutionLog.sequence)).where(
                    AgentExecutionLog.workflow_id == workflow_id
                )
            )
            or 0
        )
        # max() is 0 both for "no rows" and for "one row at sequence 0"; the row
        # count disambiguates.
        if persisted:
            next_sequence += 1

        executions = result.get("node_executions") or []
        if not executions:
            executions = [
                {
                    "node": agent_result.get("agent_name", "unknown"),
                    "status": agent_result.get("status", "failed"),
                    "execution_time_ms": 0.0,
                    "tool_calls": agent_result.get("tool_calls") or [],
                    "confidence": agent_result.get("confidence"),
                    "summary": agent_result.get("summary"),
                }
                for agent_result in result.get("agent_results", [])
            ]

        already_written = _resumed_prefix_length(
            persisted, [execution.get("node", "unknown") for execution in executions]
        )
        for offset, execution in enumerate(executions[already_written:]):
            session.add(
                AgentExecutionLog(
                    workflow_id=workflow_id,
                    agent_name=execution.get("node", "unknown"),
                    execution_time_ms=int(execution.get("execution_time_ms") or 0),
                    status=(
                        "completed"
                        if execution.get("status") == "success"
                        else "failed"
                    ),
                    tool_calls=len(execution.get("tool_calls") or []),
                    confidence=execution.get("confidence"),
                    summary=execution.get("summary"),
                    sequence=next_sequence + offset,
                )
            )

    async def _mark_running(self, workflow_id: uuid.UUID) -> None:
        """Flip the run to ``running`` before the graph starts."""
        async with self._session_factory() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
            if workflow is None:
                raise WorkflowNotFoundError(str(workflow_id))
            workflow.workflow_status = WorkflowStatus.RUNNING
            await session.commit()

    async def _mark_waiting_for_hitl(
        self, workflow_id: uuid.UUID, result: Dict
    ) -> None:
        """Park the run for human review (SRS §38 steps 2-4)."""
        async with self._session_factory() as session:
            workflow = await session.get(WorkflowRun, workflow_id)
            if workflow is None:
                return
            workflow.workflow_status = WorkflowStatus.WAITING_FOR_HITL
            workflow.current_node = result.get("current_node")

            # The reviewer decides from this record, so it must be on the row
            # before the workflow is advertised as awaiting approval.
            assessment = extract_risk_assessment(result)
            if assessment is not None:
                workflow.risk_assessment = assessment

            # Persist the partial trace too: the dashboard shows how far a
            # parked workflow got while the reviewer decides.
            await self._persist_trace(session, workflow_id, result)
            session.add(
                AuditLog(
                    workflow_id=workflow_id,
                    action=json.dumps(
                        {
                            "event": "hitl_requested",
                            "risk_score": result.get("risk_score"),
                            "reasons": (assessment or {}).get("reasons", []),
                        }
                    ),
                    performed_by=AUDIT_ACTOR,
                )
            )
            await session.commit()

        logger.info(
            "workflow_id=%s paused for human approval risk_score=%s",
            workflow_id,
            result.get("risk_score"),
        )

    async def _mark_failed(self, workflow_id: uuid.UUID, reason: str) -> None:
        """Record a non-recoverable failure (SRS §35)."""
        try:
            async with self._session_factory() as session:
                workflow = await session.get(WorkflowRun, workflow_id)
                if workflow is not None:
                    workflow.workflow_status = WorkflowStatus.FAILED
                    workflow.completed_at = func.now()
                session.add(
                    AuditLog(
                        workflow_id=workflow_id,
                        action=json.dumps(
                            {"event": "workflow_failed", "reason": reason}
                        ),
                        performed_by=AUDIT_ACTOR,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - failure bookkeeping must not mask the cause
            logger.exception(
                "workflow_id=%s could not record failure", workflow_id
            )

    async def _audit(self, workflow_id: uuid.UUID, action: Dict) -> None:
        """Append one audit row, swallowing bookkeeping failures."""
        try:
            async with self._session_factory() as session:
                session.add(
                    AuditLog(
                        workflow_id=workflow_id,
                        action=json.dumps(action),
                        performed_by=AUDIT_ACTOR,
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - auditing must not break execution
            logger.exception("workflow_id=%s audit write failed", workflow_id)
