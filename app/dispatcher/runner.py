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
from typing import Any, Dict, Optional

from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.graph.nodes.aggregator import CONTEXT_KEY as AGGREGATION_KEY
from app.graph.state import build_initial_state
from app.models import AgentExecutionLog, AuditLog, SupportTicket, WorkflowRun
from app.models.enums import SubscriptionPlan, TicketStatus, WorkflowStatus
from app.services.exceptions import WorkflowNotFoundError

logger = logging.getLogger(__name__)

AUDIT_ACTOR = "workflow-dispatcher"

#: Graph interrupt marker in the result of ``ainvoke``.
_INTERRUPT_KEY = "__interrupt__"


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
        config = {"configurable": {"thread_id": str(workflow_id)}}
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

            for agent_result in result.get("agent_results", []):
                session.add(
                    AgentExecutionLog(
                        workflow_id=workflow_id,
                        agent_name=agent_result.get("agent_name", "unknown"),
                        # Per-node timings are logged by the nodes themselves;
                        # the runner only sees the aggregate run.
                        execution_time_ms=0,
                        status=(
                            "completed"
                            if agent_result.get("status") == "success"
                            else "failed"
                        ),
                        tool_calls=len(agent_result.get("tool_calls") or []),
                    )
                )

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
            session.add(
                AuditLog(
                    workflow_id=workflow_id,
                    action=json.dumps(
                        {
                            "event": "hitl_requested",
                            "risk_score": result.get("risk_score"),
                            "reasons": (result.get("shared_context") or {})
                            .get("risk", {})
                            .get("reasons", []),
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
