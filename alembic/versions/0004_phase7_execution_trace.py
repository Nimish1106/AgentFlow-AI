"""Phase 7 execution trace + structured risk assessment.

Two read-path additions the Phase 7 operations dashboard needs. Both extend the
SRS §18 schema rather than replacing any of it - every original column keeps its
meaning.

1. ``agent_execution_logs`` gains ``confidence``, ``summary`` and ``sequence``.
   §18.6 already carries ``execution_time_ms`` and ``tool_calls``, but the
   dispatcher had no per-node timings to write and the schema had nowhere to
   keep a confidence score or a human-readable line.

   - ``confidence`` - the reasoning node's own LLM confidence. NULL for the
     deterministic governance nodes (aggregator, risk engine, dispatcher), which
     do not reason and therefore have no confidence to report.
   - ``summary``    - one-line description of what the node did.
   - ``sequence``   - ordinal position in the trace. Required for correct
     ordering: parallel domain agents finish inside the same superstep and share
     ``created_at`` to sub-second precision, so timestamps alone cannot order
     them. Rows are appended across resumes, never rewritten, so the sequence is
     also what makes a resumed run's trace read continuously.

2. ``workflow_runs`` gains ``risk_assessment`` (JSON).

   The Risk Engine's decision - ``score``, ``level``, ``requires_hitl``,
   ``reasons`` - is what the HITL approval drawer shows a reviewer before they
   release money. It lives in GraphState, which the API deliberately does not
   read (checkpoints are the graph's private storage), so the dispatcher now
   projects it onto the workflow row. Storing it structurally keeps the review
   packet robust: no parsing of log prose, and re-wording a log line can never
   silently blank the risk shown to a reviewer.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-01

"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "agent_execution_logs",
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.add_column(
        "agent_execution_logs",
        sa.Column("summary", sa.Text(), nullable=True),
    )
    # Existing rows predate the trace and have no known ordering; 0 keeps them
    # readable and stable rather than inventing a sequence for them.
    op.add_column(
        "agent_execution_logs",
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
    )

    # Nullable: a workflow that fails before the Risk Engine runs never produced
    # an assessment, and an empty dict would be indistinguishable from "no risk".
    op.add_column(
        "workflow_runs",
        sa.Column("risk_assessment", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "risk_assessment")
    op.drop_column("agent_execution_logs", "sequence")
    op.drop_column("agent_execution_logs", "summary")
    op.drop_column("agent_execution_logs", "confidence")
