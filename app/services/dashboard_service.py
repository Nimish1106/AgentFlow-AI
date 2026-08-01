"""Read-only queries backing the Phase 7 operations dashboard.

Scope and rationale
-------------------
SRS §36 specifies only single-resource reads, while SRS §5 makes the React app a
monitoring and HITL approval console. A console cannot list anything through
``GET /tickets/{ticket_id}``, so this service adds the collection and trace reads
the dashboard needs.

Everything here is a projection of data the platform already persists
(``support_tickets``, ``workflow_runs``, ``agent_execution_logs``, ``users``,
``subscriptions``, ``invoices``). No new business behaviour, no writes, no LLM
and no MCP - the dashboard observes the system, it never drives it. Approving a
workflow still goes through ``ApprovalService`` (SRS §38).

All queries are SQLAlchemy Core/ORM constructs, so values are parameterised
(SRS §43).
"""

import logging
import uuid
from typing import Dict, List, Optional, Tuple

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AgentExecutionLog,
    Invoice,
    Subscription,
    SupportTicket,
    User,
    WorkflowRun,
)
from app.models.enums import TicketStatus, WorkflowStatus
from app.services.exceptions import WorkflowNotFoundError

logger = logging.getLogger(__name__)

#: Default page size for the list endpoints.
DEFAULT_LIMIT = 50

#: Statuses counted as "active" on the metrics cards: a run the platform is
#: still working on. ``waiting_for_hitl`` is deliberately excluded - it has its
#: own card and is blocked on a human, not executing.
ACTIVE_WORKFLOW_STATUSES = (WorkflowStatus.PENDING, WorkflowStatus.RUNNING)

#: Most recent invoices to show a reviewer as billing context.
REVIEW_INVOICE_LIMIT = 5


class DashboardService:
    """Serves the operations dashboard's read models."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ----------------------------------------------------------------- tickets

    async def list_tickets(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        status: Optional[TicketStatus] = None,
    ) -> Tuple[List[Dict], int]:
        """Return ticket rows joined to their latest workflow, newest first."""
        latest_workflow = self._latest_workflow_subquery()

        query: Select = (
            select(SupportTicket, User, Subscription.plan, WorkflowRun)
            .join(User, User.id == SupportTicket.customer_id)
            .outerjoin(Subscription, Subscription.user_id == SupportTicket.customer_id)
            .outerjoin(
                latest_workflow,
                latest_workflow.c.ticket_id == SupportTicket.id,
            )
            .outerjoin(
                WorkflowRun,
                WorkflowRun.workflow_id == latest_workflow.c.workflow_id,
            )
            .order_by(SupportTicket.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_query: Select = select(func.count()).select_from(SupportTicket)
        if status is not None:
            query = query.where(SupportTicket.status == status)
            count_query = count_query.where(SupportTicket.status == status)

        rows = (await self._session.execute(query)).all()
        total = int((await self._session.scalar(count_query)) or 0)

        items = [
            {
                "id": ticket.id,
                "customer_id": ticket.customer_id,
                "customer_name": user.full_name,
                "company_name": user.company_name,
                "customer_tier": plan.value if plan is not None else "basic",
                "title": ticket.title,
                "priority": ticket.priority.value,
                "status": ticket.status.value,
                "created_at": ticket.created_at,
                "workflow_id": workflow.workflow_id if workflow else None,
                "workflow_status": (
                    workflow.workflow_status.value if workflow else None
                ),
                "current_node": workflow.current_node if workflow else None,
                "requires_hitl": bool(
                    workflow
                    and workflow.workflow_status == WorkflowStatus.WAITING_FOR_HITL
                ),
            }
            for ticket, user, plan, workflow in rows
        ]
        return items, total

    # --------------------------------------------------------------- workflows

    async def list_workflows(
        self,
        *,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0,
        status: Optional[WorkflowStatus] = None,
    ) -> Tuple[List[Dict], int]:
        """Return workflow rows with ticket and customer context, newest first."""
        query: Select = (
            select(WorkflowRun, SupportTicket, User)
            .join(SupportTicket, SupportTicket.id == WorkflowRun.ticket_id)
            .join(User, User.id == SupportTicket.customer_id)
            .order_by(WorkflowRun.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_query: Select = select(func.count()).select_from(WorkflowRun)
        if status is not None:
            query = query.where(WorkflowRun.workflow_status == status)
            count_query = count_query.where(WorkflowRun.workflow_status == status)

        rows = (await self._session.execute(query)).all()
        total = int((await self._session.scalar(count_query)) or 0)

        items = [
            {
                "workflow_id": workflow.workflow_id,
                "ticket_id": workflow.ticket_id,
                "ticket_title": ticket.title,
                "customer_id": ticket.customer_id,
                "customer_name": user.full_name,
                "workflow_status": workflow.workflow_status.value,
                "current_node": workflow.current_node,
                "requires_hitl": (
                    workflow.workflow_status == WorkflowStatus.WAITING_FOR_HITL
                ),
                "started_at": workflow.started_at,
                "completed_at": workflow.completed_at,
                "duration_ms": _duration_ms(workflow),
            }
            for workflow, ticket, user in rows
        ]
        return items, total

    async def get_workflow_trace(self, workflow_id: uuid.UUID) -> Dict:
        """Return a workflow's ordered execution trace (SRS §18.6).

        Raises:
            WorkflowNotFoundError: no such workflow run.
        """
        workflow = await self._session.get(WorkflowRun, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(str(workflow_id))

        steps = await self._trace_steps(workflow_id)
        return {
            "workflow_id": workflow.workflow_id,
            "workflow_status": workflow.workflow_status.value,
            "current_node": workflow.current_node,
            "requires_hitl": (
                workflow.workflow_status == WorkflowStatus.WAITING_FOR_HITL
            ),
            "risk_score": _risk_field(workflow, "score"),
            "steps": steps,
        }

    # --------------------------------------------------------------- approvals

    async def get_approval_detail(self, workflow_id: uuid.UUID) -> Dict:
        """Assemble the full review packet for a paused workflow (SRS §38).

        Returns the ticket, the customer's billing context and the risk reasons
        the Risk Engine recorded, so a reviewer never has to leave the drawer.
        Works for any workflow, not just paused ones - a reviewer often wants to
        read the packet of a run that was already decided.

        Raises:
            WorkflowNotFoundError: no such workflow run.
        """
        row = (
            await self._session.execute(
                select(WorkflowRun, SupportTicket, User)
                .join(SupportTicket, SupportTicket.id == WorkflowRun.ticket_id)
                .join(User, User.id == SupportTicket.customer_id)
                .where(WorkflowRun.workflow_id == workflow_id)
            )
        ).first()
        if row is None:
            raise WorkflowNotFoundError(str(workflow_id))
        workflow, ticket, user = row

        subscription = await self._session.scalar(
            select(Subscription).where(Subscription.user_id == user.id).limit(1)
        )
        invoices = list(
            await self._session.scalars(
                select(Invoice)
                .where(Invoice.user_id == user.id)
                .order_by(Invoice.created_at.desc())
                .limit(REVIEW_INVOICE_LIMIT)
            )
        )
        steps = await self._trace_steps(workflow_id)

        return {
            "workflow_id": workflow.workflow_id,
            "ticket_id": ticket.id,
            "ticket_title": ticket.title,
            "issue_text": ticket.description,
            "customer_id": user.id,
            "customer_name": user.full_name,
            "company_name": user.company_name,
            "customer_tier": (
                subscription.plan.value if subscription is not None else "basic"
            ),
            "priority": ticket.priority.value,
            "workflow_status": workflow.workflow_status.value,
            # Straight off the workflow row: the Risk Engine's own decision,
            # exactly as it made it (SRS §39).
            "risk_score": _risk_field(workflow, "score"),
            "risk_level": _risk_field(workflow, "level"),
            "reasons": list(_risk_field(workflow, "reasons") or []),
            # Only reasoning nodes carry a confidence; the deterministic nodes
            # would add noise to a reviewer's summary list.
            "agent_summaries": [
                step for step in steps if step["confidence"] is not None
            ],
            "subscription": (
                {
                    "plan": subscription.plan.value,
                    "monthly_price": float(subscription.monthly_price),
                    "renewal_date": subscription.renewal_date,
                    "subscription_status": subscription.subscription_status.value,
                }
                if subscription is not None
                else None
            ),
            "invoices": [
                {
                    "id": invoice.id,
                    "amount": float(invoice.amount),
                    "currency": invoice.currency,
                    "payment_status": invoice.payment_status.value,
                    "created_at": invoice.created_at,
                }
                for invoice in invoices
            ],
        }

    # ----------------------------------------------------------------- metrics

    async def get_metrics(self) -> Dict:
        """Return the header metrics cards.

        ``avg_execution_time_ms`` averages the *total* execution time of
        completed runs - the sum of their node timings - not individual nodes,
        so the card reads as "how long a ticket takes to resolve".
        """
        counts = dict(
            (
                await self._session.execute(
                    select(
                        WorkflowRun.workflow_status,
                        func.count(WorkflowRun.workflow_id),
                    ).group_by(WorkflowRun.workflow_status)
                )
            ).all()
        )

        per_workflow_totals = (
            select(func.sum(AgentExecutionLog.execution_time_ms).label("total"))
            .join(
                WorkflowRun,
                WorkflowRun.workflow_id == AgentExecutionLog.workflow_id,
            )
            .where(WorkflowRun.workflow_status == WorkflowStatus.COMPLETED)
            .group_by(AgentExecutionLog.workflow_id)
            .subquery()
        )
        avg_execution_time = await self._session.scalar(
            select(func.avg(per_workflow_totals.c.total))
        )

        open_tickets = await self._session.scalar(
            select(func.count())
            .select_from(SupportTicket)
            .where(
                SupportTicket.status.in_(
                    (TicketStatus.OPEN, TicketStatus.IN_PROGRESS)
                )
            )
        )

        return {
            "active_workflows": sum(
                int(counts.get(status, 0)) for status in ACTIVE_WORKFLOW_STATUSES
            ),
            "pending_hitl_approvals": int(
                counts.get(WorkflowStatus.WAITING_FOR_HITL, 0)
            ),
            "avg_execution_time_ms": (
                int(avg_execution_time) if avg_execution_time else None
            ),
            "completed_workflows": int(counts.get(WorkflowStatus.COMPLETED, 0)),
            "failed_workflows": int(counts.get(WorkflowStatus.FAILED, 0)),
            "open_tickets": int(open_tickets or 0),
        }

    # ----------------------------------------------------------------- helpers

    def _latest_workflow_subquery(self):
        """Subquery selecting each ticket's most recent workflow id.

        A ticket can be retried, so ``workflow_runs`` may hold several rows per
        ticket; the hub shows the newest.
        """
        newest = (
            select(
                WorkflowRun.ticket_id.label("ticket_id"),
                func.max(WorkflowRun.started_at).label("started_at"),
            )
            .group_by(WorkflowRun.ticket_id)
            .subquery()
        )
        return (
            select(
                WorkflowRun.ticket_id.label("ticket_id"),
                WorkflowRun.workflow_id.label("workflow_id"),
            )
            .join(
                newest,
                (newest.c.ticket_id == WorkflowRun.ticket_id)
                & (newest.c.started_at == WorkflowRun.started_at),
            )
            .subquery()
        )

    async def _trace_steps(self, workflow_id: uuid.UUID) -> List[Dict]:
        """Return execution-log rows ordered by their recorded sequence."""
        logs = await self._session.scalars(
            select(AgentExecutionLog)
            .where(AgentExecutionLog.workflow_id == workflow_id)
            .order_by(AgentExecutionLog.sequence, AgentExecutionLog.created_at)
        )
        return [
            {
                "sequence": log.sequence,
                "agent_name": log.agent_name,
                "status": log.status,
                "execution_time_ms": log.execution_time_ms,
                "tool_calls": log.tool_calls,
                "confidence": log.confidence,
                "summary": log.summary,
                "created_at": log.created_at,
            }
            for log in logs
        ]


def _duration_ms(workflow: WorkflowRun) -> Optional[int]:
    """Wall-clock duration of a finished run, in milliseconds."""
    if workflow.completed_at is None:
        return None
    delta = workflow.completed_at - workflow.started_at
    return max(int(delta.total_seconds() * 1000), 0)


def _risk_field(workflow: WorkflowRun, field: str):
    """Read one field of the persisted Risk Engine assessment (SRS §39).

    ``workflow_runs.risk_assessment`` is written by the dispatcher straight from
    the Risk Engine's own output, so governance data the reviewer sees is never
    re-derived from prose. Returns None when the Risk Engine never ran.
    """
    assessment = workflow.risk_assessment
    if not isinstance(assessment, dict):
        return None
    return assessment.get(field)
