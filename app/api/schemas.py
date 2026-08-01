"""Pydantic request/response schemas (SRS §26, §36)."""

import uuid
from datetime import date, datetime

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


# --------------------------------------------------------------------------- #
# Operations dashboard read models (Phase 7).
#
# SRS §36 defines only single-resource reads, but SRS §5 makes the React app a
# monitoring and approval console - which cannot list anything through
# ``GET /tickets/{id}`` alone. These are strictly read-only projections of data
# the platform already persists; no new business behaviour lives here.
# --------------------------------------------------------------------------- #


class TicketSummary(BaseModel):
    """One row of the ticket & workflow operations hub."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    customer_id: uuid.UUID
    customer_name: str
    company_name: str
    customer_tier: str
    title: str
    priority: str
    status: str
    created_at: datetime
    workflow_id: uuid.UUID | None = None
    workflow_status: str | None = None
    current_node: str | None = None
    requires_hitl: bool = False


class TicketListResponse(BaseModel):
    """Paginated ticket list."""

    model_config = ConfigDict(from_attributes=True)

    items: list[TicketSummary]
    total: int


class WorkflowSummary(BaseModel):
    """One row of the workflow monitor."""

    model_config = ConfigDict(from_attributes=True)

    workflow_id: uuid.UUID
    ticket_id: uuid.UUID
    ticket_title: str
    customer_id: uuid.UUID
    customer_name: str
    workflow_status: str
    current_node: str | None = None
    requires_hitl: bool = False
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: int | None = None


class WorkflowListResponse(BaseModel):
    """Paginated workflow list."""

    model_config = ConfigDict(from_attributes=True)

    items: list[WorkflowSummary]
    total: int


class TraceStep(BaseModel):
    """One node in a workflow's execution trace (SRS §18.6)."""

    model_config = ConfigDict(from_attributes=True)

    sequence: int
    agent_name: str
    status: str
    execution_time_ms: int
    tool_calls: int
    confidence: float | None = None
    summary: str | None = None
    created_at: datetime


class WorkflowTraceResponse(BaseModel):
    """Execution trace for the live timeline view."""

    model_config = ConfigDict(from_attributes=True)

    workflow_id: uuid.UUID
    workflow_status: str
    current_node: str | None = None
    requires_hitl: bool = False
    risk_score: float | None = None
    steps: list[TraceStep]


class InvoiceSummary(BaseModel):
    """Invoice context shown to a reviewer."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    amount: float
    currency: str
    payment_status: str
    created_at: datetime


class SubscriptionSummary(BaseModel):
    """Subscription context shown to a reviewer."""

    model_config = ConfigDict(from_attributes=True)

    plan: str
    monthly_price: float
    renewal_date: date
    subscription_status: str


class ApprovalDetailResponse(BaseModel):
    """Everything a reviewer needs to decide, in one payload (SRS §38).

    Mirrors the graph's own ``build_approval_request`` so the UI and the HITL
    node agree on what a review decision is based on.
    """

    model_config = ConfigDict(from_attributes=True)

    workflow_id: uuid.UUID
    ticket_id: uuid.UUID
    ticket_title: str
    issue_text: str
    customer_id: uuid.UUID
    customer_name: str
    company_name: str
    customer_tier: str
    priority: str
    workflow_status: str
    risk_score: float | None = None
    risk_level: str | None = None
    reasons: list[str] = []
    agent_summaries: list[TraceStep] = []
    subscription: SubscriptionSummary | None = None
    invoices: list[InvoiceSummary] = []


class MetricsResponse(BaseModel):
    """Status metrics cards on the dashboard header."""

    model_config = ConfigDict(from_attributes=True)

    active_workflows: int
    pending_hitl_approvals: int
    avg_execution_time_ms: int | None = None
    completed_workflows: int
    failed_workflows: int
    open_tickets: int
