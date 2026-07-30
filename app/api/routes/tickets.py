"""Ticket endpoints (SRS §36). Routes validate and delegate; no business logic."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_ticket_service
from app.api.schemas import TicketDetailResponse, TicketRequest, TicketResponse
from app.config.settings import get_settings
from app.services.exceptions import CustomerNotFoundError, TicketNotFoundError
from app.services.ticket_service import TicketService

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post(
    "", status_code=status.HTTP_202_ACCEPTED, response_model=TicketResponse
)
async def create_ticket(
    payload: TicketRequest,
    service: TicketService = Depends(get_ticket_service),
) -> TicketResponse:
    """Accept a ticket, create its workflow, enqueue it, and return 202 immediately."""
    try:
        workflow = await service.create_ticket_workflow(payload)
    except CustomerNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found"
        )
    return TicketResponse(
        workflow_id=workflow.workflow_id,
        status="accepted",
        estimated_wait_time=get_settings().estimated_wait_time_seconds,
    )


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
async def get_ticket(
    ticket_id: uuid.UUID,
    service: TicketService = Depends(get_ticket_service),
) -> TicketDetailResponse:
    """Return ticket details and its latest workflow, if any."""
    try:
        ticket, workflow = await service.get_ticket(ticket_id)
    except TicketNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found"
        )
    return TicketDetailResponse(
        id=ticket.id,
        customer_id=ticket.customer_id,
        title=ticket.title,
        description=ticket.description,
        priority=ticket.priority.value,
        status=ticket.status.value,
        created_at=ticket.created_at,
        workflow_id=workflow.workflow_id if workflow else None,
        workflow_status=workflow.workflow_status.value if workflow else None,
    )
