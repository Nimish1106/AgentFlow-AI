"""Unit tests for TicketService Phase 3 additions (update, internal notes)."""

import uuid

import pytest
from sqlalchemy import select

from app.models import SupportTicket, TicketNote, User
from app.models.enums import TicketPriority, TicketStatus
from app.services.exceptions import TicketNotFoundError
from app.services.ticket_service import TicketService


async def _make_ticket(session) -> SupportTicket:
    user = User(
        company_name="Acme Corp",
        full_name="Alice Admin",
        email=f"{uuid.uuid4()}@acme.test",
    )
    session.add(user)
    await session.flush()
    ticket = SupportTicket(
        customer_id=user.id,
        title="Charged twice",
        description="Duplicate invoice this month.",
    )
    session.add(ticket)
    await session.commit()
    return ticket


async def test_update_ticket_status_and_priority(session_factory):
    async with session_factory() as session:
        ticket = await _make_ticket(session)

        updated = await TicketService(session).update_ticket(
            ticket.id,
            status=TicketStatus.IN_PROGRESS,
            priority=TicketPriority.HIGH,
        )
        assert updated.status is TicketStatus.IN_PROGRESS
        assert updated.priority is TicketPriority.HIGH


async def test_update_ticket_partial(session_factory):
    async with session_factory() as session:
        ticket = await _make_ticket(session)

        updated = await TicketService(session).update_ticket(
            ticket.id, status=TicketStatus.RESOLVED
        )
        assert updated.status is TicketStatus.RESOLVED
        assert updated.priority is TicketPriority.MEDIUM  # unchanged default


async def test_update_ticket_missing(session_factory):
    async with session_factory() as session:
        with pytest.raises(TicketNotFoundError):
            await TicketService(session).update_ticket(
                uuid.uuid4(), status=TicketStatus.CLOSED
            )


async def test_add_internal_note(session_factory):
    async with session_factory() as session:
        ticket = await _make_ticket(session)

        note = await TicketService(session).add_internal_note(
            ticket.id, "billing_agent", "Duplicate confirmed; refund eligible."
        )
        assert note.ticket_id == ticket.id
        assert note.author == "billing_agent"

        stored = await session.scalar(
            select(TicketNote).where(TicketNote.ticket_id == ticket.id)
        )
        assert stored is not None
        assert stored.note == "Duplicate confirmed; refund eligible."


async def test_add_internal_note_missing_ticket(session_factory):
    async with session_factory() as session:
        with pytest.raises(TicketNotFoundError):
            await TicketService(session).add_internal_note(
                uuid.uuid4(), "agent", "note"
            )


async def test_create_workflow_requires_queue(session_factory):
    async with session_factory() as session:
        service = TicketService(session)  # no queue
        with pytest.raises(RuntimeError):
            await service.create_ticket_workflow(object())
