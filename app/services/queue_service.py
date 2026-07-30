"""Workflow queue operations backed by Redis Streams (SRS §8, §19)."""

import logging
import uuid

import redis.asyncio as redis

from app.config.settings import get_settings

logger = logging.getLogger(__name__)


class QueueService:
    """Pushes workflow jobs onto the Redis Stream consumed by the engine (Phase 2)."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client
        self._stream = get_settings().workflow_stream

    async def enqueue_workflow(
        self, workflow_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> str:
        """Append a workflow job to the stream and return the stream entry id."""
        entry_id = await self._client.xadd(
            self._stream,
            {"workflow_id": str(workflow_id), "ticket_id": str(ticket_id)},
        )
        logger.info(
            "workflow_id=%s enqueued to stream=%s entry=%s",
            workflow_id,
            self._stream,
            entry_id,
        )
        return entry_id
