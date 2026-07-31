"""Tests for the Risk Engine node (SRS §39)."""

import pytest

from app.config.settings import Settings
from app.graph.constants import AgentName
from app.graph.nodes.aggregator import CONTEXT_KEY as AGGREGATION_KEY
from app.graph.nodes.risk_engine import (
    CONTEXT_KEY,
    NODE_NAME,
    RISK_SCORES,
    assess_risk,
    extract_refund_amount,
    find_sensitive_operations,
    risk_engine_node,
)
from app.graph.state import AgentResult, build_initial_state


@pytest.fixture(autouse=True)
def fixed_thresholds(monkeypatch):
    """Pin governance thresholds so tests do not depend on the local .env."""
    import app.graph.nodes.risk_engine as risk_engine

    settings = Settings(
        hitl_refund_threshold=1000.0, hitl_confidence_threshold=0.6
    )
    monkeypatch.setattr(risk_engine, "get_settings", lambda: settings)
    return settings


def result(
    name: str,
    *,
    status: str = "success",
    confidence: float = 0.9,
    output_data: dict | None = None,
) -> AgentResult:
    """Build an AgentResult with the uniform contract shape."""
    return AgentResult(
        agent_name=name,
        status=status,
        summary=f"{name} done",
        confidence=confidence,
        actions_taken=[],
        tool_calls=[],
        output_data=output_data or {},
    )


def policy(approved: bool = True, risk: str = "low") -> AgentResult:
    """Policy Agent result carrying a verdict."""
    return result(
        AgentName.POLICY.value, output_data={"approved": approved, "risk": risk}
    )


def state_with(*results: AgentResult, conflicts: list[str] | None = None):
    """Initial state carrying results and an optional aggregation record."""
    state = build_initial_state(
        workflow_id="wf_risk",
        ticket_id="tkt_1",
        customer_id="cust_1",
        issue_text="I was charged twice.",
    )
    state["agent_results"] = list(results)
    state["shared_context"] = {
        AGGREGATION_KEY: {"conflicts": conflicts or []},
    }
    return state


class TestRefundAmountExtraction:
    def test_reads_an_eligible_refund_amount(self):
        amount = extract_refund_amount(
            [
                result(
                    AgentName.BILLING.value,
                    output_data={"refund_eligible": True, "refund_amount": 250.0},
                )
            ]
        )
        assert amount == 250.0

    def test_ignores_amounts_without_eligibility(self):
        """An invoice merely looked up is not money leaving the business."""
        amount = extract_refund_amount(
            [
                result(
                    AgentName.BILLING.value,
                    output_data={"invoice_amount": 5000.0},
                )
            ]
        )
        assert amount is None

    def test_coerces_string_amounts(self):
        amount = extract_refund_amount(
            [
                result(
                    AgentName.BILLING.value,
                    output_data={"eligible": True, "refund_amount": "199.99"},
                )
            ]
        )
        assert amount == pytest.approx(199.99)

    def test_unparseable_amount_is_ignored(self):
        amount = extract_refund_amount(
            [
                result(
                    AgentName.BILLING.value,
                    output_data={"eligible": True, "refund_amount": "lots"},
                )
            ]
        )
        assert amount is None

    def test_takes_the_largest_of_several(self):
        amount = extract_refund_amount(
            [
                result(
                    AgentName.BILLING.value,
                    output_data={"eligible": True, "refund_amount": 100.0},
                ),
                result(
                    AgentName.ACCOUNT.value,
                    output_data={"eligible": True, "refund_amount": 900.0},
                ),
            ]
        )
        assert amount == 900.0


class TestSensitiveOperations:
    def test_detects_a_permission_change(self):
        found = find_sensitive_operations(
            [result(AgentName.ACCOUNT.value, output_data={"permission_change": True})]
        )
        assert found == [f"{AgentName.ACCOUNT.value}.permission_change"]

    def test_ignores_falsey_markers(self):
        found = find_sensitive_operations(
            [
                result(
                    AgentName.ACCOUNT.value,
                    output_data={"account_suspended": False},
                )
            ]
        )
        assert found == []

    def test_a_routine_unlock_is_not_sensitive(self):
        """SRS §30.6: unlocking a dashboard is routine, not sensitive."""
        found = find_sensitive_operations(
            [
                result(
                    AgentName.ACCOUNT.value,
                    output_data={"dashboard_unlocked": True},
                )
            ]
        )
        assert found == []


class TestRiskAssessment:
    def test_clean_low_risk_workflow_needs_no_human(self):
        assessment = assess_risk(
            state_with(
                result(
                    AgentName.BILLING.value,
                    output_data={"refund_eligible": True, "refund_amount": 199.99},
                ),
                policy(approved=True, risk="low"),
            )
        )
        assert assessment["risk_level"] == "low"
        assert assessment["requires_hitl"] is False
        assert assessment["risk_score"] == RISK_SCORES["low"]

    def test_refund_above_threshold_requires_approval(self):
        assessment = assess_risk(
            state_with(
                result(
                    AgentName.BILLING.value,
                    output_data={"refund_eligible": True, "refund_amount": 5000.0},
                ),
                policy(approved=True, risk="low"),
            )
        )
        assert assessment["requires_hitl"] is True
        assert assessment["risk_level"] == "high"
        assert any("exceeds threshold" in r for r in assessment["reasons"])

    def test_refund_exactly_at_threshold_does_not_trip(self):
        """The threshold is exclusive: 'above' means strictly greater."""
        assessment = assess_risk(
            state_with(
                result(
                    AgentName.BILLING.value,
                    output_data={"refund_eligible": True, "refund_amount": 1000.0},
                ),
                policy(),
            )
        )
        assert assessment["requires_hitl"] is False

    def test_sensitive_operation_requires_approval(self):
        assessment = assess_risk(
            state_with(
                result(
                    AgentName.ACCOUNT.value,
                    output_data={"permission_change": True},
                ),
                policy(),
            )
        )
        assert assessment["requires_hitl"] is True
        assert assessment["risk_level"] == "high"

    def test_policy_rejection_requires_approval(self):
        assessment = assess_risk(state_with(policy(approved=False, risk="high")))
        assert assessment["requires_hitl"] is True
        assert any("rejected" in r for r in assessment["reasons"])

    def test_failed_agent_requires_approval(self):
        """SRS §39: missing information is a risk factor."""
        assessment = assess_risk(
            state_with(
                result(AgentName.BILLING.value, status="failed"),
                policy(),
            )
        )
        assert assessment["requires_hitl"] is True
        assert assessment["risk_level"] == "medium"
        assert any("incomplete information" in r for r in assessment["reasons"])

    def test_low_confidence_requires_approval(self):
        assessment = assess_risk(
            state_with(
                result(AgentName.BILLING.value, confidence=0.3),
                policy(),
            )
        )
        assert assessment["requires_hitl"] is True
        assert any("below" in r for r in assessment["reasons"])

    def test_confidence_at_threshold_does_not_trip(self):
        assessment = assess_risk(
            state_with(result(AgentName.BILLING.value, confidence=0.6), policy())
        )
        assert assessment["requires_hitl"] is False

    def test_policy_high_risk_alone_escalates_to_hitl(self):
        """A high risk level always needs a human, even if approved."""
        assessment = assess_risk(state_with(policy(approved=True, risk="high")))
        assert assessment["risk_level"] == "high"
        assert assessment["requires_hitl"] is True

    def test_policy_medium_risk_does_not_force_hitl(self):
        assessment = assess_risk(state_with(policy(approved=True, risk="medium")))
        assert assessment["risk_level"] == "medium"
        assert assessment["requires_hitl"] is False

    def test_conflicts_raise_risk_without_forcing_hitl(self):
        assessment = assess_risk(
            state_with(policy(), conflicts=["billing vs policy"])
        )
        assert assessment["risk_level"] == "medium"
        assert any("conflicting" in r for r in assessment["reasons"])

    def test_worst_factor_sets_the_level(self):
        assessment = assess_risk(
            state_with(
                result(AgentName.BILLING.value, status="failed"),
                result(
                    AgentName.ACCOUNT.value,
                    output_data={"account_suspended": True},
                ),
                policy(),
            )
        )
        assert assessment["risk_level"] == "high"

    def test_no_factors_reports_an_explicit_reason(self):
        assessment = assess_risk(state_with(policy()))
        assert assessment["reasons"] == ["no risk factors detected"]

    def test_workflow_with_no_results_is_low_risk(self):
        assessment = assess_risk(state_with())
        assert assessment["risk_level"] == "low"
        assert assessment["requires_hitl"] is False


class TestRiskEngineNode:
    async def test_writes_risk_score_and_hitl_flag_to_state(self):
        update = await risk_engine_node(
            state_with(policy(approved=False, risk="high"))
        )
        assert update["requires_hitl"] is True
        assert update["risk_score"] == RISK_SCORES["high"]
        assert update["current_node"] == NODE_NAME

    async def test_publishes_the_assessment_into_shared_context(self):
        update = await risk_engine_node(state_with(policy()))
        assessment = update["shared_context"][CONTEXT_KEY]
        assert assessment["risk_level"] == "low"
        assert "reasons" in assessment

    async def test_returns_only_its_own_shared_context_contribution(self):
        update = await risk_engine_node(state_with(policy()))
        assert set(update["shared_context"]) == {CONTEXT_KEY}

    async def test_overrides_the_policy_agents_raw_risk_score(self):
        """The Risk Engine owns risk_score (SRS §28 data ownership)."""
        state = state_with(
            result(
                AgentName.BILLING.value,
                output_data={"refund_eligible": True, "refund_amount": 9999.0},
            ),
            policy(approved=True, risk="low"),
        )
        state["risk_score"] = RISK_SCORES["low"]
        update = await risk_engine_node(state)
        assert update["risk_score"] == RISK_SCORES["high"]
