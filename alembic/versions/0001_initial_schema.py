"""Initial Phase 1 schema (SRS §18).

Revision ID: 0001
Revises:
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

account_status = sa.Enum("active", "locked", "suspended", name="account_status")
user_role = sa.Enum("admin", "member", name="user_role")
subscription_plan = sa.Enum("basic", "premium", "enterprise", name="subscription_plan")
subscription_status = sa.Enum(
    "active", "cancelled", "expired", name="subscription_status"
)
payment_status = sa.Enum(
    "paid", "pending", "duplicate", "refunded", name="payment_status"
)
ticket_priority = sa.Enum("low", "medium", "high", "critical", name="ticket_priority")
ticket_status = sa.Enum(
    "open", "in_progress", "resolved", "closed", name="ticket_status"
)
workflow_status = sa.Enum(
    "pending", "running", "waiting_for_hitl", "completed", "failed",
    name="workflow_status",
)

ALL_ENUMS = [
    account_status,
    user_role,
    subscription_plan,
    subscription_status,
    payment_status,
    ticket_priority,
    ticket_status,
    workflow_status,
]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("account_status", account_status, nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("plan", subscription_plan, nullable=False),
        sa.Column("monthly_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("renewal_date", sa.Date(), nullable=False),
        sa.Column("subscription_status", subscription_status, nullable=False),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])

    op.create_table(
        "invoices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("payment_status", payment_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_invoices_user_id", "invoices", ["user_id"])

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "customer_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", ticket_priority, nullable=False),
        sa.Column("status", ticket_status, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_support_tickets_customer_id", "support_tickets", ["customer_id"]
    )

    op.create_table(
        "workflow_runs",
        sa.Column("workflow_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ticket_id",
            sa.Uuid(),
            sa.ForeignKey("support_tickets.id"),
            nullable=False,
        ),
        sa.Column("workflow_status", workflow_status, nullable=False),
        sa.Column("current_node", sa.String(255), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_runs_ticket_id", "workflow_runs", ["ticket_id"])

    op.create_table(
        "agent_execution_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_runs.workflow_id"),
            nullable=False,
        ),
        sa.Column("agent_name", sa.String(255), nullable=False),
        sa.Column("execution_time_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(50), nullable=False),
        sa.Column("tool_calls", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_agent_execution_logs_workflow_id", "agent_execution_logs", ["workflow_id"]
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "workflow_id",
            sa.Uuid(),
            sa.ForeignKey("workflow_runs.workflow_id"),
            nullable=False,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("performed_by", sa.String(255), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_logs_workflow_id", "audit_logs", ["workflow_id"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("agent_execution_logs")
    op.drop_table("workflow_runs")
    op.drop_table("support_tickets")
    op.drop_table("invoices")
    op.drop_table("subscriptions")
    op.drop_table("users")
    for enum_type in ALL_ENUMS:
        enum_type.drop(op.get_bind(), checkfirst=True)
