"""Risk Engine node (SRS §39).

Deterministic Python - no LLM, no MCP. It reads the aggregated view plus the
Policy Agent's verdict and decides two things:

- ``risk_score`` / ``risk_level`` (low | medium | high, SRS §27)
- ``requires_hitl`` - whether a human must approve before the customer is told
  anything (SRS §38)

Decision factors (SRS §39): financial impact, sensitive operations, missing
information, low confidence, policy violations. Each factor that fires
contributes a reason string; the highest-severity factor sets the level.
Keeping this deterministic means an identical workflow state always produces an
identical governance decision - an LLM here would make approvals unauditable.
"""

import logging
import time
from typing import Dict, Iterable, List, Optional, Tuple

from app.config.settings import get_settings
from app.graph.constants import AgentName
from app.graph.nodes.aggregator import CONTEXT_KEY as AGGREGATION_KEY
from app.graph.state import AgentResult, GraphState

logger = logging.getLogger(__name__)

NODE_NAME = "risk_engine"

#: shared_context key holding the risk assessment.
CONTEXT_KEY = "risk"

#: SRS §27 risk levels mapped onto the numeric GraphState.risk_score.
RISK_SCORES: Dict[str, float] = {"low": 0.2, "medium": 0.5, "high": 0.9}

#: Severity ordering so the worst factor wins.
_LEVEL_ORDER: Tuple[str, ...] = ("low", "medium", "high")

#: output_data keys naming a sensitive operation that always needs a human
#: (SRS §38: account suspension, permission changes).
_SENSITIVE_KEYS: Tuple[str, ...] = (
    "account_suspended",
    "permission_change",
    "permissions_changed",
    "feature_flag_changed",
)

#: output_data keys that may carry a refund amount.
_AMOUNT_KEYS: Tuple[str, ...] = ("refund_amount", "amount", "invoice_amount")


def _max_level(levels: Iterable[str]) -> str:
    """Return the highest-severity level, defaulting to ``low``."""
    return max(levels, key=_LEVEL_ORDER.index, default="low")


def _coerce_amount(value: object) -> Optional[float]:
    """Best-effort numeric coercion for amounts that arrive as strings."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def extract_refund_amount(results: List[AgentResult]) -> Optional[float]:
    """Return the largest refund amount any agent proposed, if any.

    Amounts only count when the same agent also reports eligibility, so an
    invoice merely *looked up* does not read as money leaving the business.
    """
    amounts: List[float] = []
    for result in results:
        output = result.get("output_data") or {}
        eligible = output.get("refund_eligible", output.get("eligible"))
        if eligible is not True:
            continue
        for key in _AMOUNT_KEYS:
            amount = _coerce_amount(output.get(key))
            if amount is not None:
                amounts.append(amount)
                break
    return max(amounts) if amounts else None


def find_sensitive_operations(results: List[AgentResult]) -> List[str]:
    """List sensitive operations agents performed or proposed (SRS §38)."""
    found: List[str] = []
    for result in results:
        output = result.get("output_data") or {}
        for key in _SENSITIVE_KEYS:
            if output.get(key):
                found.append(f"{result.get('agent_name', 'unknown')}.{key}")
    return found


def assess_risk(state: GraphState) -> Dict:
    """Score workflow risk and decide whether HITL approval is required.

    Returns a dict with ``risk_level``, ``risk_score``, ``requires_hitl`` and
    the ``reasons`` that drove the decision (SRS §39 output contract).
    """
    settings = get_settings()
    results = list(state.get("agent_results", []))
    aggregation = (state.get("shared_context") or {}).get(AGGREGATION_KEY, {})

    reasons: List[str] = []
    levels: List[str] = ["low"]
    hitl = False

    # Financial impact: a refund above the configured threshold needs a human.
    amount = extract_refund_amount(results)
    if amount is not None and amount > settings.hitl_refund_threshold:
        reasons.append(
            f"refund amount {amount:.2f} exceeds threshold "
            f"{settings.hitl_refund_threshold:.2f}"
        )
        levels.append("high")
        hitl = True

    # Sensitive operations always need a human (SRS §38).
    for operation in find_sensitive_operations(results):
        reasons.append(f"sensitive operation: {operation}")
        levels.append("high")
        hitl = True

    # Policy violations: a rejection is the policy gate refusing the action.
    policy = next(
        (r for r in results if r.get("agent_name") == AgentName.POLICY.value),
        None,
    )
    if policy is not None and policy.get("output_data", {}).get("approved") is False:
        reasons.append("policy_agent rejected the proposed resolution")
        levels.append("high")
        hitl = True
    if policy is not None:
        levels.append(str(policy.get("output_data", {}).get("risk", "low")))

    # Conflicting recommendations were resolved in policy's favour, but the
    # disagreement itself raises risk (SRS §40).
    conflicts = aggregation.get("conflicts") or []
    if conflicts:
        reasons.append(f"{len(conflicts)} conflicting agent recommendation(s)")
        levels.append("medium")

    # Missing information: any agent that failed leaves the picture incomplete.
    failed = [r["agent_name"] for r in results if r.get("status") == "failed"]
    if failed:
        reasons.append(f"incomplete information: {', '.join(failed)} failed")
        levels.append("medium")
        hitl = True

    # Low confidence in any successful agent (SRS §38).
    for result in results:
        if result.get("status") != "success":
            continue
        confidence = float(result.get("confidence", 0.0))
        if confidence < settings.hitl_confidence_threshold:
            reasons.append(
                f"{result['agent_name']} confidence {confidence:.2f} below "
                f"threshold {settings.hitl_confidence_threshold:.2f}"
            )
            levels.append("medium")
            hitl = True

    level = _max_level(levels)
    # High risk always needs a human even when no single factor demanded it.
    if level == "high":
        hitl = True

    return {
        "risk_level": level,
        "risk_score": RISK_SCORES[level],
        "requires_hitl": hitl,
        "reasons": reasons or ["no risk factors detected"],
    }


async def risk_engine_node(state: GraphState) -> Dict:
    """Assess risk and return the GraphState update (SRS §39)."""
    started = time.perf_counter()
    workflow_id = state.get("workflow_id", "")

    assessment = assess_risk(state)

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "workflow_id=%s node=%s risk_level=%s risk_score=%.2f requires_hitl=%s "
        "reasons=%s execution_time_ms=%.1f retry_count=%s",
        workflow_id,
        NODE_NAME,
        assessment["risk_level"],
        assessment["risk_score"],
        assessment["requires_hitl"],
        assessment["reasons"],
        elapsed_ms,
        state.get("retry_count", 0),
    )

    return {
        "current_node": NODE_NAME,
        "risk_score": assessment["risk_score"],
        "requires_hitl": assessment["requires_hitl"],
        "shared_context": {CONTEXT_KEY: assessment},
    }
