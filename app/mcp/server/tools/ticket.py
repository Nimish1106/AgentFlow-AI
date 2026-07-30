"""Ticket tool namespace for the Enterprise MCP Server (SRS §31)."""

from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.schemas import NoteResult, TicketResult
from app.mcp.server.runtime import parse_uuid, run_tool
from app.models.enums import TicketPriority, TicketStatus
from app.services.ticket_service import TicketService


def _ticket_payload(ticket) -> dict:
    return TicketResult(
        id=str(ticket.id),
        customer_id=str(ticket.customer_id),
        title=ticket.title,
        description=ticket.description,
        priority=ticket.priority.value,
        status=ticket.status.value,
    ).model_dump(mode="json")


def register(mcp: FastMCP) -> None:
    """Register ticket tools on the server."""

    @mcp.tool(name="ticket_get_ticket")
    async def ticket_get_ticket(
        ticket_id: str, workflow_id: Optional[str] = None
    ) -> dict:
        """Fetch a support ticket by id."""

        async def handler(session: AsyncSession) -> dict:
            ticket, _ = await TicketService(session).get_ticket(
                parse_uuid(ticket_id, "ticket_id")
            )
            return _ticket_payload(ticket)

        return await run_tool(
            "ticket_get_ticket",
            handler,
            arguments={"ticket_id": ticket_id},
            workflow_id=workflow_id,
        )

    @mcp.tool(name="ticket_update_ticket")
    async def ticket_update_ticket(
        ticket_id: str,
        status: Optional[str] = None,
        priority: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> dict:
        """Update a ticket's status and/or priority.

        Valid statuses: open, in_progress, resolved, closed.
        Valid priorities: low, medium, high, critical.
        """

        async def handler(session: AsyncSession) -> dict:
            new_status = _parse_enum(TicketStatus, status, "status")
            new_priority = _parse_enum(TicketPriority, priority, "priority")
            ticket = await TicketService(session).update_ticket(
                parse_uuid(ticket_id, "ticket_id"),
                status=new_status,
                priority=new_priority,
            )
            return _ticket_payload(ticket)

        return await run_tool(
            "ticket_update_ticket",
            handler,
            arguments={
                "ticket_id": ticket_id,
                "status": status,
                "priority": priority,
            },
            workflow_id=workflow_id,
        )

    @mcp.tool(name="ticket_add_internal_note")
    async def ticket_add_internal_note(
        ticket_id: str,
        author: str,
        note: str,
        workflow_id: Optional[str] = None,
    ) -> dict:
        """Attach an internal (non-customer-facing) note to a ticket."""

        async def handler(session: AsyncSession) -> dict:
            ticket_note = await TicketService(session).add_internal_note(
                parse_uuid(ticket_id, "ticket_id"), author, note
            )
            return NoteResult(
                id=str(ticket_note.id),
                ticket_id=str(ticket_note.ticket_id),
                author=ticket_note.author,
                note=ticket_note.note,
            ).model_dump(mode="json")

        return await run_tool(
            "ticket_add_internal_note",
            handler,
            arguments={"ticket_id": ticket_id, "author": author},
            workflow_id=workflow_id,
        )


def _parse_enum(enum_cls, value: Optional[str], field_name: str):
    """Convert an optional string into its enum member, or raise ValueError."""
    if value is None:
        return None
    try:
        return enum_cls(value)
    except ValueError as exc:
        valid = ", ".join(member.value for member in enum_cls)
        raise ValueError(
            f"{field_name} must be one of: {valid} (got {value!r})"
        ) from exc
