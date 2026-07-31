"""Phase 6 governance: ticket resolution column.

SRS §36 requires ``GET /tickets/{ticket_id}`` to return ticket details *and* the
resolution, but the §18.4 schema defines no column for it. This adds one so the
completed workflow's customer-facing response is persistent business data in
PostgreSQL (SRS §28), not something the API has to reconstruct from a
LangGraph checkpoint.

The LangGraph checkpoint tables (``checkpoints``, ``checkpoint_blobs``,
``checkpoint_writes``, ``checkpoint_migrations``) are created and migrated by
``AsyncPostgresSaver.setup()`` on dispatcher boot, not by Alembic - the saver
owns its own schema version.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-31

"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "support_tickets",
        sa.Column("resolution", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("support_tickets", "resolution")
