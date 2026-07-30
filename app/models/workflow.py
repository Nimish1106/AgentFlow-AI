"""Workflow execution ORM models (SRS §18.5–§18.7)."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import WorkflowStatus, as_db_enum


class WorkflowRun(Base):
    """One LangGraph execution for a ticket."""

    __tablename__ = "workflow_runs"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("support_tickets.id"), index=True, nullable=False
    )
    workflow_status: Mapped[WorkflowStatus] = mapped_column(
        as_db_enum(WorkflowStatus, "workflow_status"),
        default=WorkflowStatus.PENDING,
        nullable=False,
    )
    current_node: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentExecutionLog(Base):
    """Execution history for every agent run inside a workflow."""

    __tablename__ = "agent_execution_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workflow_runs.workflow_id"), index=True, nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(255), nullable=False)
    execution_time_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(Base):
    """Immutable record of critical business actions."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workflow_runs.workflow_id"), index=True, nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    performed_by: Mapped[str] = mapped_column(String(255), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
