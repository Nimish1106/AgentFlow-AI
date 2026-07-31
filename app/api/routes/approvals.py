"""HITL approval endpoint (SRS §36, §38). Routes validate and delegate."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_approval_service
from app.api.schemas import ApprovalRequest, ApprovalResponse
from app.graph.nodes.hitl import APPROVED, REJECTED
from app.services.approval_service import ApprovalService
from app.services.exceptions import (
    WorkflowNotAwaitingApprovalError,
    WorkflowNotFoundError,
)

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.post("/{workflow_id}", response_model=ApprovalResponse)
async def approve_workflow(
    workflow_id: uuid.UUID,
    payload: ApprovalRequest,
    service: ApprovalService = Depends(get_approval_service),
) -> ApprovalResponse:
    """Record a reviewer's decision and resume the paused workflow (SRS §38)."""
    try:
        workflow = await service.approve(workflow_id, payload)
    except WorkflowNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
        )
    except WorkflowNotAwaitingApprovalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Workflow is not awaiting approval (status: {exc.workflow_status})",
        )
    return ApprovalResponse(
        workflow_id=workflow.workflow_id,
        approval_status=APPROVED if payload.approved else REJECTED,
        workflow_status=workflow.workflow_status.value,
    )
