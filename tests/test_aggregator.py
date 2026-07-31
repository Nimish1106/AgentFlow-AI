"""Tests for the Results Aggregator node (SRS §40)."""

from app.graph.constants import AgentName
from app.graph.nodes.aggregator import (
    CONTEXT_KEY,
    NODE_NAME,
    aggregator_node,
    deduplicate_results,
    detect_conflicts,
    merge_output_data,
)
from app.graph.state import AgentResult, build_initial_state


def result(
    name: str,
    *,
    status: str = "success",
    confidence: float = 0.9,
    summary: str = "",
    output_data: dict | None = None,
) -> AgentResult:
    """Build an AgentResult with the uniform contract shape."""
    return AgentResult(
        agent_name=name,
        status=status,
        summary=summary or f"{name} done",
        confidence=confidence,
        actions_taken=[],
        tool_calls=[],
        output_data=output_data or {},
    )


def state_with(*results: AgentResult, **overrides):
    """Initial state carrying the given AgentResults."""
    state = build_initial_state(
        workflow_id="wf_agg",
        ticket_id="tkt_1",
        customer_id="cust_1",
        issue_text="I was charged twice.",
    )
    state["agent_results"] = list(results)
    state.update(overrides)
    return state


class TestDeduplication:
    def test_keeps_one_result_per_agent(self):
        merged = deduplicate_results(
            [
                result(AgentName.BILLING.value, summary="first"),
                result(AgentName.BILLING.value, summary="second"),
            ]
        )
        assert len(merged) == 1

    def test_keeps_the_most_recent_result(self):
        """A retried agent appends again; the later attempt is authoritative."""
        merged = deduplicate_results(
            [
                result(AgentName.BILLING.value, status="failed", summary="first"),
                result(AgentName.BILLING.value, summary="second"),
            ]
        )
        assert merged[0]["summary"] == "second"
        assert merged[0]["status"] == "success"

    def test_preserves_first_appearance_order(self):
        merged = deduplicate_results(
            [
                result(AgentName.BILLING.value),
                result(AgentName.ACCOUNT.value),
                result(AgentName.BILLING.value, summary="retry"),
            ]
        )
        assert [r["agent_name"] for r in merged] == [
            AgentName.BILLING.value,
            AgentName.ACCOUNT.value,
        ]

    def test_empty_input_yields_empty_output(self):
        assert deduplicate_results([]) == []


class TestConflictDetection:
    def test_domain_recommendation_against_policy_rejection_is_a_conflict(self):
        conflicts = detect_conflicts(
            [
                result(
                    AgentName.BILLING.value,
                    output_data={"refund_eligible": True},
                ),
                result(
                    AgentName.POLICY.value,
                    output_data={"approved": False, "risk": "high"},
                ),
            ]
        )
        assert len(conflicts) == 1
        assert "policy_agent wins" in conflicts[0]

    def test_agreement_is_not_a_conflict(self):
        conflicts = detect_conflicts(
            [
                result(
                    AgentName.BILLING.value,
                    output_data={"refund_eligible": True},
                ),
                result(
                    AgentName.POLICY.value,
                    output_data={"approved": True, "risk": "low"},
                ),
            ]
        )
        assert conflicts == []

    def test_no_policy_result_means_no_conflict_can_be_judged(self):
        conflicts = detect_conflicts(
            [result(AgentName.BILLING.value, output_data={"refund_eligible": True})]
        )
        assert conflicts == []

    def test_agent_without_a_recommendation_never_conflicts(self):
        conflicts = detect_conflicts(
            [
                result(AgentName.TECHNICAL.value, output_data={"retrieval": "ok"}),
                result(
                    AgentName.POLICY.value,
                    output_data={"approved": False, "risk": "high"},
                ),
            ]
        )
        assert conflicts == []

    def test_failed_agent_recommendation_is_ignored(self):
        """A failed agent's output is not a recommendation to weigh."""
        conflicts = detect_conflicts(
            [
                result(
                    AgentName.BILLING.value,
                    status="failed",
                    output_data={"refund_eligible": True},
                ),
                result(
                    AgentName.POLICY.value,
                    output_data={"approved": False, "risk": "high"},
                ),
            ]
        )
        assert conflicts == []

    def test_policy_without_a_verdict_yields_no_conflict(self):
        conflicts = detect_conflicts(
            [
                result(
                    AgentName.BILLING.value,
                    output_data={"refund_eligible": True},
                ),
                result(AgentName.POLICY.value, output_data={"risk": "low"}),
            ]
        )
        assert conflicts == []


class TestOutputMerging:
    def test_namespaces_findings_under_agent_names(self):
        merged = merge_output_data(
            [
                result(AgentName.BILLING.value, output_data={"invoice_status": "dup"}),
                result(AgentName.ACCOUNT.value, output_data={"account_status": "ok"}),
            ]
        )
        assert merged == {
            AgentName.BILLING.value: {"invoice_status": "dup"},
            AgentName.ACCOUNT.value: {"account_status": "ok"},
        }

    def test_excludes_failed_agents(self):
        merged = merge_output_data(
            [result(AgentName.BILLING.value, status="failed", output_data={"a": 1})]
        )
        assert merged == {}


class TestAggregatorNode:
    async def test_publishes_the_aggregation_into_shared_context(self):
        update = await aggregator_node(
            state_with(
                result(AgentName.BILLING.value, confidence=0.8),
                result(AgentName.POLICY.value, output_data={"approved": True}),
            )
        )
        aggregation = update["shared_context"][CONTEXT_KEY]
        assert aggregation["agent_count"] == 2
        assert aggregation["successful_agents"] == [
            AgentName.BILLING.value,
            AgentName.POLICY.value,
        ]
        assert aggregation["confidences"][AgentName.BILLING.value] == 0.8

    async def test_separates_failed_agents(self):
        update = await aggregator_node(
            state_with(
                result(AgentName.BILLING.value),
                result(AgentName.ACCOUNT.value, status="failed"),
            )
        )
        aggregation = update["shared_context"][CONTEXT_KEY]
        assert aggregation["failed_agents"] == [AgentName.ACCOUNT.value]
        assert aggregation["successful_agents"] == [AgentName.BILLING.value]

    async def test_records_conflicts_for_the_audit_trail(self):
        update = await aggregator_node(
            state_with(
                result(
                    AgentName.BILLING.value, output_data={"refund_eligible": True}
                ),
                result(AgentName.POLICY.value, output_data={"approved": False}),
            )
        )
        assert update["shared_context"][CONTEXT_KEY]["conflicts"]

    async def test_sets_current_node(self):
        update = await aggregator_node(state_with())
        assert update["current_node"] == NODE_NAME

    async def test_does_not_rewrite_agent_results(self):
        """agent_results carries operator.add - re-emitting them would duplicate."""
        update = await aggregator_node(state_with(result(AgentName.BILLING.value)))
        assert "agent_results" not in update

    async def test_returns_only_its_own_shared_context_contribution(self):
        update = await aggregator_node(
            state_with(
                result(AgentName.BILLING.value),
                shared_context={"intent": "duplicate charge"},
            )
        )
        assert set(update["shared_context"]) == {CONTEXT_KEY}

    async def test_handles_a_workflow_with_no_agent_results(self):
        update = await aggregator_node(state_with())
        aggregation = update["shared_context"][CONTEXT_KEY]
        assert aggregation["agent_count"] == 0
        assert aggregation["findings"] == {}
