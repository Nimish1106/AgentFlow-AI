"""Phase 3 MCP support: feature flags, ticket notes, nullable audit workflow FK.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-30

"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "feature_flags", sa.JSON(), server_default="{}", nullable=False
        ),
    )

    op.create_table(
        "ticket_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ticket_id",
            sa.Uuid(),
            sa.ForeignKey("support_tickets.id"),
            nullable=False,
        ),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_ticket_notes_ticket_id", "ticket_notes", ["ticket_id"])

    op.alter_column("audit_logs", "workflow_id", nullable=True)


def downgrade() -> None:
    op.alter_column("audit_logs", "workflow_id", nullable=False)
    op.drop_table("ticket_notes")
    op.drop_column("users", "feature_flags")
