"""Ticket business logic: creation, workflow row, queueing (kept out of routes)."""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import TicketRequest
from app.models import SupportTicket, User, WorkflowRun
from app.services.exceptions import CustomerNotFoundError, TicketNotFoundError
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)


class TicketService:
    """Creates tickets and their workflow runs, and reads ticket details."""

    def __init__(self, session: AsyncSession, queue: QueueService) -> None:
        self._session = session
        self._queue = queue

    async def create_ticket_workflow(self, request: TicketRequest) -> WorkflowRun:
        """Persist a ticket + pending workflow run and enqueue it for execution.

        The DB transaction commits only after the enqueue succeeds, so a queue
        failure never leaves an orphaned workflow row.
        """
        customer = await self._session.get(User, request.customer_id)
        if customer is None:
            raise CustomerNotFoundError(str(request.customer_id))

        ticket = SupportTicket(
            customer_id=customer.id,
            title=request.subject,
            description=request.description,
        )
        self._session.add(ticket)
        await self._session.flush()

        workflow = WorkflowRun(ticket_id=ticket.id)
        self._session.add(workflow)
        await self._session.flush()

        await self._queue.enqueue_workflow(workflow.workflow_id, ticket.id)
        await self._session.commit()

        logger.info(
            "workflow_id=%s created for ticket_id=%s", workflow.workflow_id, ticket.id
        )
        return workflow

    async def get_ticket(
        self, ticket_id: uuid.UUID
    ) -> tuple[SupportTicket, WorkflowRun | None]:
        """Return a ticket and its most recent workflow run."""
        ticket = await self._session.get(SupportTicket, ticket_id)
        if ticket is None:
            raise TicketNotFoundError(str(ticket_id))

        workflow = await self._session.scalar(
            select(WorkflowRun)
            .where(WorkflowRun.ticket_id == ticket_id)
            .order_by(WorkflowRun.started_at.desc())
            .limit(1)
        )
        return ticket, workflow
