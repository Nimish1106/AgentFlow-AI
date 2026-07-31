"""FastAPI dependency wiring for services."""

import redis.asyncio as redis
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.redis import get_redis
from app.database.session import get_db
from app.services.approval_service import ApprovalService
from app.services.queue_service import QueueService
from app.services.ticket_service import TicketService
from app.services.workflow_service import WorkflowService


def get_ticket_service(
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> TicketService:
    """Build a TicketService with a request-scoped session and queue."""
    return TicketService(session, QueueService(redis_client))


def get_approval_service(
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> ApprovalService:
    """Build an ApprovalService with a request-scoped session and queue."""
    return ApprovalService(session, QueueService(redis_client))


def get_workflow_service(
    session: AsyncSession = Depends(get_db),
) -> WorkflowService:
    """Build a WorkflowService with a request-scoped session."""
    return WorkflowService(session)
