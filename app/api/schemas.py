"""Pydantic request/response schemas (SRS §26, §36)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TicketRequest(BaseModel):
    """Ticket submission payload (SRS §26)."""

    model_config = ConfigDict(from_attributes=True)

    customer_id: uuid.UUID
    subject: str = Field(min_length=1, max_length=500)
    description: str = Field(min_length=1)


class TicketResponse(BaseModel):
    """202 response for an accepted ticket (SRS §26)."""

    model_config = ConfigDict(from_attributes=True)

    workflow_id: uuid.UUID
    status: str
    estimated_wait_time: int


class WorkflowStatusResponse(BaseModel):
    """Workflow status payload (SRS §26, §36)."""

    model_config = ConfigDict(from_attributes=True)

    workflow_id: uuid.UUID
    current_node: str | None
    workflow_status: str
    completed_agents: list[str]
    requires_hitl: bool


class ApprovalRequest(BaseModel):
    """HITL approval decision (SRS §26, §36 POST /approvals/{workflow_id})."""

    model_config = ConfigDict(from_attributes=True)

    approved: bool
    reviewer_name: str = Field(min_length=1, max_length=255)
    comments: str = ""


class ApprovalResponse(BaseModel):
    """Acknowledgement that a paused workflow was queued for resume."""

    model_config = ConfigDict(from_attributes=True)

    workflow_id: uuid.UUID
    approval_status: str
    workflow_status: str


class TicketDetailResponse(BaseModel):
    """Ticket details plus its latest workflow (SRS §36 GET /tickets/{id})."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    title: str
    description: str
    priority: str
    status: str
    created_at: datetime
    resolution: str | None = None
    workflow_id: uuid.UUID | None = None
    workflow_status: str | None = None


class HealthResponse(BaseModel):
    """Service health payload."""

    status: str
    database: str
    redis: str
