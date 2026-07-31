"""Workflow queue operations backed by Redis Streams (SRS §8, §19).

Two job kinds share one stream so ordering per workflow is preserved:

- ``start``  - run a new workflow from its initial state
- ``resume`` - resume a workflow parked at the HITL interrupt (SRS §38)

The consumer (``app.dispatcher``) dispatches on the ``kind`` field. Redis holds
only this transient job envelope - the decision itself is audited in PostgreSQL
before the job is queued, because Redis is not a permanent store (SRS §19).
"""

import json
import logging
import uuid
from typing import Optional

import redis.asyncio as redis

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

KIND_START = "start"
KIND_RESUME = "resume"


class QueueService:
    """Pushes workflow jobs onto the Redis Stream consumed by the dispatcher."""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client
        self._stream = get_settings().workflow_stream

    async def enqueue_workflow(
        self, workflow_id: uuid.UUID, ticket_id: uuid.UUID
    ) -> str:
        """Append a new-workflow job to the stream and return the entry id."""
        return await self._enqueue(
            {
                "kind": KIND_START,
                "workflow_id": str(workflow_id),
                "ticket_id": str(ticket_id),
            }
        )

    async def enqueue_resume(
        self,
        workflow_id: uuid.UUID,
        ticket_id: uuid.UUID,
        *,
        approved: bool,
        reviewer_name: str,
        comments: str = "",
    ) -> str:
        """Append a resume-after-approval job to the stream (SRS §38).

        The reviewer's decision travels as the LangGraph resume value, so the
        dispatcher never has to re-read it from anywhere else.
        """
        return await self._enqueue(
            {
                "kind": KIND_RESUME,
                "workflow_id": str(workflow_id),
                "ticket_id": str(ticket_id),
                "decision": json.dumps(
                    {
                        "approved": approved,
                        "reviewer_name": reviewer_name,
                        "comments": comments,
                    }
                ),
            }
        )

    async def _enqueue(self, fields: dict) -> str:
        """Append one job envelope to the stream."""
        entry_id = await self._client.xadd(self._stream, fields)
        logger.info(
            "workflow_id=%s kind=%s enqueued to stream=%s entry=%s",
            fields.get("workflow_id"),
            fields.get("kind"),
            self._stream,
            entry_id,
        )
        return entry_id


def parse_decision(fields: dict) -> Optional[dict]:
    """Read the reviewer decision out of a resume job envelope.

    Returns ``None`` when the envelope carries no parseable decision, so the
    caller can fail the job rather than resume with an unknown verdict.
    """
    raw = fields.get("decision")
    if not raw:
        return None
    try:
        decision = json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("unparseable resume decision payload: %r", raw)
        return None
    if not isinstance(decision, dict) or "approved" not in decision:
        logger.warning("resume decision missing 'approved': %r", decision)
        return None
    return decision
