"""Operations dashboard read endpoints (Phase 7).

Routes validate and delegate; every query lives in ``DashboardService``.

These extend the SRS §36 REST surface, which defines only single-resource reads.
SRS §5 makes the React app a monitoring and HITL approval console, and a console
cannot list anything through ``GET /tickets/{ticket_id}`` alone. Everything here
is read-only: listing, tracing and counting data the platform already persists.
The only state-changing endpoint the dashboard uses is the existing
``POST /approvals/{workflow_id}`` (SRS §38).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.dependencies import get_dashboard_service
from app.api.schemas import (
    ApprovalDetailResponse,
    MetricsResponse,
    TicketListResponse,
    TicketSummary,
    WorkflowListResponse,
    WorkflowSummary,
    WorkflowTraceResponse,
)
from app.models.enums import TicketStatus, WorkflowStatus
from app.services.dashboard_service import DEFAULT_LIMIT, DashboardService
from app.services.exceptions import WorkflowNotFoundError

router = APIRouter(tags=["dashboard"])

#: Upper bound on a single page. Caps the work one request can ask the database
#: for, so a mistyped query string cannot pull the whole table.
MAX_LIMIT = 200


@router.get("/tickets", response_model=TicketListResponse)
async def list_tickets(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    ticket_status: TicketStatus | None = Query(None, alias="status"),
    service: DashboardService = Depends(get_dashboard_service),
) -> TicketListResponse:
    """List support tickets with their latest workflow, newest first."""
    items, total = await service.list_tickets(
        limit=limit, offset=offset, status=ticket_status
    )
    return TicketListResponse(
        items=[TicketSummary(**item) for item in items], total=total
    )


@router.get("/workflows", response_model=WorkflowListResponse)
async def list_workflows(
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    workflow_status: WorkflowStatus | None = Query(None, alias="status"),
    service: DashboardService = Depends(get_dashboard_service),
) -> WorkflowListResponse:
    """List workflow runs with ticket and customer context, newest first."""
    items, total = await service.list_workflows(
        limit=limit, offset=offset, status=workflow_status
    )
    return WorkflowListResponse(
        items=[WorkflowSummary(**item) for item in items], total=total
    )


@router.get("/workflows/{workflow_id}/trace", response_model=WorkflowTraceResponse)
async def get_workflow_trace(
    workflow_id: uuid.UUID,
    service: DashboardService = Depends(get_dashboard_service),
) -> WorkflowTraceResponse:
    """Return a workflow's step-by-step execution trace (SRS §18.6)."""
    try:
        trace = await service.get_workflow_trace(workflow_id)
    except WorkflowNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
        )
    return WorkflowTraceResponse(**trace)


@router.get(
    "/workflows/{workflow_id}/approval", response_model=ApprovalDetailResponse
)
async def get_approval_detail(
    workflow_id: uuid.UUID,
    service: DashboardService = Depends(get_dashboard_service),
) -> ApprovalDetailResponse:
    """Return the full review packet for a workflow (SRS §38)."""
    try:
        detail = await service.get_approval_detail(workflow_id)
    except WorkflowNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found"
        )
    return ApprovalDetailResponse(**detail)


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    service: DashboardService = Depends(get_dashboard_service),
) -> MetricsResponse:
    """Return the dashboard's status metrics cards."""
    return MetricsResponse(**await service.get_metrics())
