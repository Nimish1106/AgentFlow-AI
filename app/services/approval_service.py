"""HITL approval business logic (SRS §38), kept out of FastAPI routes.

The endpoint's job is only to record the human decision durably and hand the
workflow back to the dispatcher. It must not run the graph itself: FastAPI never
calls an LLM or MCP (SRS §46), and a resume can take as long as the remaining
workflow does.

Sequence:

1. Load the workflow run and refuse anything not parked at ``waiting_for_hitl``.
2. Write the decision to ``audit_logs`` - every business action is auditable
   (SRS §16.10), and the audit row must exist before the resume is queued so an
   approval is never invisible.
3. Flip the run to ``running`` and enqueue a ``resume`` job carrying the verdict.
"""

import json
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ApprovalRequest
from app.models import AuditLog, WorkflowRun
from app.models.enums import WorkflowStatus
from app.services.exceptions import (
    WorkflowNotAwaitingApprovalError,
    WorkflowNotFoundError,
)
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)

AUDIT_ACTOR_PREFIX = "reviewer"


class ApprovalService:
    """Records HITL decisions and queues the workflow resume (SRS §38)."""

    def __init__(self, session: AsyncSession, queue: QueueService) -> None:
        self._session = session
        self._queue = queue

    async def approve(
        self, workflow_id: uuid.UUID, request: ApprovalRequest
    ) -> WorkflowRun:
        """Audit a review decision and queue the paused workflow for resume.

        Raises:
            WorkflowNotFoundError: no such workflow run.
            WorkflowNotAwaitingApprovalError: the run is not paused for review.
        """
        workflow = await self._session.get(WorkflowRun, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(str(workflow_id))
        if workflow.workflow_status != WorkflowStatus.WAITING_FOR_HITL:
            raise WorkflowNotAwaitingApprovalError(
                str(workflow_id), workflow.workflow_status.value
            )

        self._session.add(
            AuditLog(
                workflow_id=workflow.workflow_id,
                action=json.dumps(
                    {
                        "event": "hitl_decision",
                        "approved": request.approved,
                        "comments": request.comments,
                    }
                ),
                performed_by=f"{AUDIT_ACTOR_PREFIX}:{request.reviewer_name}",
            )
        )

        # The run is unpaused from here on; the dispatcher picks it up next.
        workflow.workflow_status = WorkflowStatus.RUNNING
        await self._session.flush()

        await self._queue.enqueue_resume(
            workflow.workflow_id,
            workflow.ticket_id,
            approved=request.approved,
            reviewer_name=request.reviewer_name,
            comments=request.comments,
        )
        await self._session.commit()

        logger.info(
            "workflow_id=%s hitl decision approved=%s queued for resume",
            workflow.workflow_id,
            request.approved,
        )
        return workflow
