"""Workflow status endpoint (SRS §36)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import get_workflow_service
from app.api.schemas import WorkflowStatusResponse
from app.models.enums import WorkflowStatus
from app.services.exceptions import WorkflowNotFoundError
from app.services.workflow_service import WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/{workflow_id}", response_model=WorkflowStatusResponse)
async def get_workflow_status(
    workflow_id: uuid.UUID,
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowStatusResponse:
    """Return the current status of a workflow run."""
    try:
        workflow, completed_agents = await service.get_workflow_status(workflow_id)
    except WorkflowNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
        )
    return WorkflowStatusResponse(
        workflow_id=workflow.workflow_id,
        current_node=workflow.current_node,
        workflow_status=workflow.workflow_status.value,
        completed_agents=completed_agents,
        requires_hitl=workflow.workflow_status == WorkflowStatus.WAITING_FOR_HITL,
    )
