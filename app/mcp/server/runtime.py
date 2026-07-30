"""Shared runtime for Enterprise MCP tools: sessions, timeouts, auditing.

Keeps every tool wrapper thin: `run_tool` opens a DB session, enforces the
tool timeout (SRS §16.8), converts domain errors into structured `ToolError`
payloads, and writes an `AuditLog` row for every call — success or failure
(SRS §16.10).
"""

import asyncio
import json
import logging
import uuid
from typing import Awaitable, Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config.settings import get_settings
from app.mcp.schemas import ToolError
from app.models import AuditLog
from app.services.exceptions import NotFoundError

logger = logging.getLogger(__name__)

AUDIT_ACTOR = "enterprise-mcp"
_MAX_AUDIT_ARGS_CHARS = 500

_session_factory: Optional[async_sessionmaker[AsyncSession]] = None


def set_session_factory(factory: async_sessionmaker[AsyncSession]) -> None:
    """Inject the session factory (tests substitute an aiosqlite factory)."""
    global _session_factory
    _session_factory = factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the configured session factory, defaulting to the app engine."""
    global _session_factory
    if _session_factory is None:
        from app.database.session import async_session_factory

        _session_factory = async_session_factory
    return _session_factory


def parse_uuid(value: str, field_name: str) -> uuid.UUID:
    """Parse a string into a UUID, raising ValueError with the field name."""
    try:
        return uuid.UUID(value)
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field_name} is not a valid UUID: {value!r}") from exc


async def run_tool(
    tool_name: str,
    handler: Callable[[AsyncSession], Awaitable[dict]],
    *,
    arguments: dict,
    workflow_id: Optional[str] = None,
) -> dict:
    """Execute a tool handler with timeout, error translation, and auditing.

    The handler receives an open session and returns the success payload.
    All failures are returned as structured ``ToolError`` dicts — exceptions
    never cross the MCP boundary.
    """
    settings = get_settings()
    factory = get_session_factory()
    try:
        async with asyncio.timeout(settings.mcp_tool_timeout_seconds):
            async with factory() as session:
                result = await handler(session)
        await _audit(tool_name, arguments, "success", workflow_id)
        return result
    except ValueError as exc:
        await _audit(tool_name, arguments, "failed", workflow_id)
        return ToolError(error=str(exc), code="invalid_input").model_dump()
    except NotFoundError as exc:
        await _audit(tool_name, arguments, "failed", workflow_id)
        return ToolError(
            error=f"{exc.__class__.__name__}: {exc}", code="not_found"
        ).model_dump()
    except TimeoutError:
        await _audit(tool_name, arguments, "failed", workflow_id)
        return ToolError(
            error=f"{tool_name} timed out after "
            f"{settings.mcp_tool_timeout_seconds}s",
            code="timeout",
        ).model_dump()
    except Exception:  # noqa: BLE001 - MCP boundary must never leak exceptions
        logger.exception("tool=%s unexpected failure", tool_name)
        await _audit(tool_name, arguments, "failed", workflow_id)
        return ToolError(
            error=f"{tool_name} failed unexpectedly", code="internal_error"
        ).model_dump()


async def _audit(
    tool_name: str,
    arguments: dict,
    status: str,
    workflow_id: Optional[str],
) -> None:
    """Persist an audit row for a tool call using a dedicated session."""
    workflow_uuid: Optional[uuid.UUID] = None
    if workflow_id:
        try:
            workflow_uuid = uuid.UUID(workflow_id)
        except ValueError:
            logger.warning("tool=%s invalid workflow_id=%r", tool_name, workflow_id)

    args_json = json.dumps(arguments, default=str)[:_MAX_AUDIT_ARGS_CHARS]
    action = json.dumps(
        {"tool": tool_name, "status": status, "arguments": args_json}
    )
    try:
        factory = get_session_factory()
        async with factory() as session:
            session.add(
                AuditLog(
                    workflow_id=workflow_uuid,
                    action=action,
                    performed_by=AUDIT_ACTOR,
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - auditing must not mask the tool result
        logger.exception("tool=%s audit write failed", tool_name)
