"""Human-in-the-Loop approval node (SRS §38).

No LLM, no MCP. The node calls LangGraph's ``interrupt()``, which raises out of
the graph run after the checkpoint is written. The workflow is then parked as
``waiting_for_hitl`` until ``POST /approvals/{workflow_id}`` resumes the same
thread with ``Command(resume=...)`` (SRS §38 implementation rule: the
``workflow_id`` *is* the ``thread_id``).

On resume, ``interrupt()`` returns the value the reviewer supplied rather than
raising, so this node body runs twice per approval: once to pause, once to
record the decision.
"""

import logging
from typing import Dict

from langgraph.types import interrupt

from app.graph.nodes.risk_engine import CONTEXT_KEY as RISK_KEY
from app.graph.state import GraphState, build_node_execution

logger = logging.getLogger(__name__)

NODE_NAME = "human_approval"

#: shared_context key holding the recorded review decision.
CONTEXT_KEY = "hitl"

APPROVED = "approved"
REJECTED = "rejected"


def build_approval_request(state: GraphState) -> Dict:
    """Describe what the reviewer is being asked to approve.

    This payload is surfaced by ``GET /workflows/{id}`` (via the checkpoint) and
    by the Phase 7 approval UI, so it must be self-contained: a reviewer should
    not need to read the graph state to make a decision.
    """
    risk = (state.get("shared_context") or {}).get(RISK_KEY, {})
    return {
        "workflow_id": state.get("workflow_id", ""),
        "ticket_id": state.get("ticket_id", ""),
        "customer_id": state.get("customer_id", ""),
        "issue_text": state.get("issue_text", ""),
        "risk_level": risk.get("risk_level", "unknown"),
        "risk_score": state.get("risk_score", 0.0),
        "reasons": risk.get("reasons", []),
        "agent_summaries": [
            {
                "agent_name": result.get("agent_name"),
                "status": result.get("status"),
                "confidence": result.get("confidence"),
                "summary": result.get("summary"),
            }
            for result in state.get("agent_results", [])
        ],
    }


def parse_decision(resume_value: object) -> Dict:
    """Normalise whatever the reviewer resumed with into a decision dict.

    Accepts a bare bool (``Command(resume=True)`` per SRS §38) or a mapping with
    ``approved`` / ``reviewer_name`` / ``comments`` (SRS §26 ApprovalRequest).
    Anything else is treated as a rejection: an unreadable decision must never
    be interpreted as consent.
    """
    if isinstance(resume_value, bool):
        return {"approved": resume_value, "reviewer_name": "", "comments": ""}
    if isinstance(resume_value, dict):
        return {
            "approved": bool(resume_value.get("approved", False)),
            "reviewer_name": str(resume_value.get("reviewer_name", "")),
            "comments": str(resume_value.get("comments", "")),
        }
    logger.warning("unparseable approval resume value type=%s", type(resume_value))
    return {"approved": False, "reviewer_name": "", "comments": "unparseable decision"}


async def hitl_node(state: GraphState) -> Dict:
    """Pause for human approval, then record the decision (SRS §38).

    The first pass raises ``GraphInterrupt`` from ``interrupt()``; the resumed
    pass receives the reviewer's decision and returns it as a state update.
    """
    workflow_id = state.get("workflow_id", "")
    logger.info(
        "workflow_id=%s node=%s awaiting human approval risk_score=%.2f",
        workflow_id,
        NODE_NAME,
        state.get("risk_score", 0.0),
    )

    resume_value = interrupt(build_approval_request(state))
    decision = parse_decision(resume_value)
    approval_status = APPROVED if decision["approved"] else REJECTED

    logger.info(
        "workflow_id=%s node=%s approval_status=%s reviewer=%s",
        workflow_id,
        NODE_NAME,
        approval_status,
        decision["reviewer_name"] or "unknown",
    )

    return {
        "current_node": NODE_NAME,
        "approval_status": approval_status,
        "workflow_status": "running",
        "shared_context": {CONTEXT_KEY: decision},
        "node_executions": [
            build_node_execution(
                node=NODE_NAME,
                status="success",
                # The wall-clock pause is however long the reviewer took; the
                # node itself does no work, so it reports no duration.
                execution_time_ms=0.0,
                summary=(
                    f"{approval_status} by "
                    f"{decision['reviewer_name'] or 'unknown reviewer'}"
                ),
            )
        ],
    }
