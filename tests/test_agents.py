"""Tests for the five Phase 4 agents (SRS §30): contracts, rules, failure modes."""

import pytest

from app.agents.account import make_account_agent_node
from app.agents.billing import make_billing_agent_node
from app.agents.policy import RISK_SCORES, make_policy_agent_node
from app.agents.response import make_response_agent_node
from app.agents.schemas import AgentOutcome, PolicyOutcome, ResponseOutcome
from app.agents.technical import make_technical_agent_node
from app.graph.constants import AgentName
from app.graph.state import build_initial_state

AGENT_RESULT_KEYS = {
    "agent_name",
    "status",
    "summary",
    "confidence",
    "actions_taken",
    "tool_calls",
    "output_data",
}


def initial_state(**overrides):
    state = build_initial_state(
        workflow_id="wf_test_001",
        ticket_id="tkt_001",
        customer_id="cust_001",
        issue_text="I was charged twice and my dashboard is locked.",
        customer_tier="enterprise",
        ticket_priority="high",
    )
    state.update(overrides)
    return state


def domain_outcome(**overrides) -> AgentOutcome:
    payload = {
        "summary": "Duplicate invoice confirmed; refund eligible.",
        "confidence": 0.92,
        "actions_taken": ["verified_invoice"],
        "output_data": {"refund_eligible": True},
    }
    payload.update(overrides)
    return AgentOutcome(**payload)


def tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class TestDomainAgentLoop:
    """The bind_tools -> ToolNode -> AgentResult loop, via the Billing Agent."""

    async def test_tool_loop_executes_calls_through_the_mcp_client(
        self, fake_agent_llm_factory, fake_mcp_client_factory
    ):
        client = fake_mcp_client_factory(
            {
                "billing_get_invoice": {"id": "inv-1", "payment_status": "duplicate"},
                "billing_calculate_refund": {"eligible": True},
            }
        )
        llm = fake_agent_llm_factory(
            outcomes={AgentOutcome: domain_outcome()},
            tool_call_batches=[
                [tool_call("billing_get_invoice", {"invoice_id": "inv-1"})],
                [
                    tool_call(
                        "billing_calculate_refund", {"invoice_id": "inv-1"}, "call_2"
                    )
                ],
            ],
        )
        node = make_billing_agent_node(llm=llm, mcp_client=client)

        update = await node(initial_state())

        assert [name for name, _ in client.calls] == [
            "billing_get_invoice",
            "billing_calculate_refund",
        ]
        assert update["tool_history"] == [
            "billing_get_invoice",
            "billing_calculate_refund",
        ]
        assert update["agent_results"][0]["tool_calls"] == [
            "billing_get_invoice",
            "billing_calculate_refund",
        ]

    async def test_workflow_id_is_injected_into_every_tool_call(
        self, fake_agent_llm_factory, fake_mcp_client_factory
    ):
        """MCP audit rows must attribute tool calls to the running workflow."""
        client = fake_mcp_client_factory({"billing_get_invoice": {"id": "inv-1"}})
        llm = fake_agent_llm_factory(
            outcomes={AgentOutcome: domain_outcome()},
            tool_call_batches=[
                [tool_call("billing_get_invoice", {"invoice_id": "inv-1"})]
            ],
        )
        await make_billing_agent_node(llm=llm, mcp_client=client)(initial_state())

        assert client.calls[0][1]["workflow_id"] == "wf_test_001"

    async def test_returns_the_standard_agent_result_contract(
        self, fake_agent_llm_factory, fake_mcp_client_factory
    ):
        llm = fake_agent_llm_factory(outcomes={AgentOutcome: domain_outcome()})
        node = make_billing_agent_node(llm=llm, mcp_client=fake_mcp_client_factory())

        update = await node(initial_state())
        result = update["agent_results"][0]

        assert set(result) == AGENT_RESULT_KEYS
        assert result["agent_name"] == AgentName.BILLING.value
        assert result["status"] == "success"
        assert result["confidence"] == 0.92

    async def test_update_touches_only_parallel_safe_keys(
        self, fake_agent_llm_factory, fake_mcp_client_factory
    ):
        """Domain agents run concurrently: only reduced keys may be written."""
        llm = fake_agent_llm_factory(outcomes={AgentOutcome: domain_outcome()})
        node = make_billing_agent_node(llm=llm, mcp_client=fake_mcp_client_factory())

        update = await node(initial_state())

        assert set(update) <= {
            "agent_results",
            "completed_agents",
            "tool_history",
            "shared_context",
            "messages",
            "errors",
        }

    async def test_output_data_is_namespaced_into_shared_context(
        self, fake_agent_llm_factory, fake_mcp_client_factory
    ):
        llm = fake_agent_llm_factory(outcomes={AgentOutcome: domain_outcome()})
        node = make_billing_agent_node(llm=llm, mcp_client=fake_mcp_client_factory())

        update = await node(initial_state())

        assert update["shared_context"] == {
            AgentName.BILLING.value: {"refund_eligible": True}
        }

    async def test_loop_stops_at_max_rounds(
        self, monkeypatch, fake_agent_llm_factory, fake_mcp_client_factory
    ):
        """A model that never stops calling tools must not loop forever."""
        from app.config.settings import get_settings

        monkeypatch.setattr(get_settings(), "agent_max_tool_rounds", 2)
        endless = [
            [tool_call("billing_get_invoice", {"invoice_id": "inv-1"}, f"c{i}")]
            for i in range(10)
        ]
        client = fake_mcp_client_factory({"billing_get_invoice": {"id": "inv-1"}})
        llm = fake_agent_llm_factory(
            outcomes={AgentOutcome: domain_outcome()}, tool_call_batches=endless
        )
        update = await make_billing_agent_node(llm=llm, mcp_client=client)(
            initial_state()
        )

        assert len(client.calls) == 2
        assert update["agent_results"][0]["status"] == "success"

    async def test_agent_failure_degrades_to_a_failed_result(
        self, fake_agent_llm_factory, fake_mcp_client_factory
    ):
        """SRS §40: continue with partial results - the branch never raises."""
        llm = fake_agent_llm_factory(outcomes={})  # no scripted outcome -> raises
        node = make_billing_agent_node(llm=llm, mcp_client=fake_mcp_client_factory())

        update = await node(initial_state())
        result = update["agent_results"][0]

        assert result["status"] == "failed"
        assert result["confidence"] == 0.0
        assert update["errors"]
        assert "workflow_status" not in update  # policy decides, not the branch

    async def test_structured_tool_error_reaches_the_llm_not_an_exception(
        self, fake_agent_llm_factory, fake_mcp_client_factory
    ):
        client = fake_mcp_client_factory(
            {"billing_get_invoice": {"error": "no such invoice", "code": "not_found"}}
        )
        llm = fake_agent_llm_factory(
            outcomes={AgentOutcome: domain_outcome(confidence=0.4)},
            tool_call_batches=[
                [tool_call("billing_get_invoice", {"invoice_id": "inv-x"})]
            ],
        )
        update = await make_billing_agent_node(llm=llm, mcp_client=client)(
            initial_state()
        )

        assert update["agent_results"][0]["status"] == "success"


class TestAgentIdentities:
    @pytest.mark.parametrize(
        ("factory", "agent"),
        [
            (make_billing_agent_node, AgentName.BILLING),
            (make_account_agent_node, AgentName.ACCOUNT),
            (make_technical_agent_node, AgentName.TECHNICAL),
        ],
    )
    async def test_each_domain_agent_reports_its_own_name(
        self, fake_agent_llm_factory, fake_mcp_client_factory, factory, agent
    ):
        llm = fake_agent_llm_factory(outcomes={AgentOutcome: domain_outcome()})
        update = await factory(llm=llm, mcp_client=fake_mcp_client_factory())(
            initial_state()
        )
        assert update["agent_results"][0]["agent_name"] == agent.value
        assert update["completed_agents"] == [agent.value]


class TestTechnicalAgentGrounding:
    async def test_technical_agent_searches_knowledge_before_answering(
        self, fake_agent_llm_factory, fake_mcp_client_factory
    ):
        client = fake_mcp_client_factory(
            {
                "knowledge_semantic_search": {
                    "status": "insufficient_information",
                    "results": [],
                }
            }
        )
        llm = fake_agent_llm_factory(
            outcomes={
                AgentOutcome: domain_outcome(
                    summary="Insufficient information found in the knowledge base.",
                    confidence=0.3,
                    output_data={"retrieval_status": "insufficient_information"},
                )
            },
            tool_call_batches=[
                [tool_call("knowledge_semantic_search", {"query": "dashboard error"})]
            ],
        )
        update = await make_technical_agent_node(llm=llm, mcp_client=client)(
            initial_state()
        )

        assert client.calls[0][0] == "knowledge_semantic_search"
        assert (
            update["agent_results"][0]["output_data"]["retrieval_status"]
            == "insufficient_information"
        )


class TestPolicyAgent:
    def policy_outcome(self, **overrides) -> PolicyOutcome:
        payload = {
            "summary": "Refund approved. Risk is low.",
            "confidence": 0.98,
            "actions_taken": ["evaluated_refund_policy"],
            "output_data": {},
            "approved": True,
            "risk": "low",
        }
        payload.update(overrides)
        return PolicyOutcome(**payload)

    async def test_verdict_lands_in_result_and_risk_score(
        self, fake_agent_llm_factory
    ):
        llm = fake_agent_llm_factory(outcomes={PolicyOutcome: self.policy_outcome()})
        update = await make_policy_agent_node(llm=llm)(initial_state())

        result = update["agent_results"][0]
        assert set(result) == AGENT_RESULT_KEYS
        assert result["output_data"]["approved"] is True
        assert result["output_data"]["risk"] == "low"
        assert update["risk_score"] == RISK_SCORES["low"]

    async def test_high_risk_maps_to_high_score(self, fake_agent_llm_factory):
        llm = fake_agent_llm_factory(
            outcomes={
                PolicyOutcome: self.policy_outcome(approved=False, risk="high")
            }
        )
        update = await make_policy_agent_node(llm=llm)(initial_state())
        assert update["risk_score"] == RISK_SCORES["high"]
        assert update["shared_context"][AgentName.POLICY.value]["approved"] is False

    async def test_prior_agent_results_are_in_the_prompt(
        self, fake_agent_llm_factory
    ):
        llm = fake_agent_llm_factory(outcomes={PolicyOutcome: self.policy_outcome()})
        prior = {
            "agent_name": "billing_agent",
            "status": "success",
            "summary": "Duplicate confirmed.",
            "confidence": 0.9,
            "actions_taken": [],
            "tool_calls": [],
            "output_data": {},
        }
        await make_policy_agent_node(llm=llm)(
            initial_state(agent_results=[prior])
        )

        _, messages = llm.structured_calls[0]
        assert "Duplicate confirmed." in messages[-1].content

    async def test_policy_makes_no_tool_calls(self, fake_agent_llm_factory):
        llm = fake_agent_llm_factory(outcomes={PolicyOutcome: self.policy_outcome()})
        update = await make_policy_agent_node(llm=llm)(initial_state())
        assert llm.bound_tools == []
        assert update["agent_results"][0]["tool_calls"] == []

    async def test_policy_failure_fails_the_workflow(self, fake_agent_llm_factory):
        """No verdict means the workflow must not proceed to a response."""
        llm = fake_agent_llm_factory(outcomes={})
        update = await make_policy_agent_node(llm=llm)(initial_state())
        assert update["workflow_status"] == "failed"
        assert update["errors"]


class TestResponseAgent:
    def response_outcome(self, **overrides) -> ResponseOutcome:
        payload = {
            "customer_response": "Hi Alice, your duplicate charge will be refunded.",
            "internal_note": "Refund approved by policy; duplicate confirmed.",
            "resolution_summary": "Duplicate charge refunded.",
            "confidence": 0.95,
        }
        payload.update(overrides)
        return ResponseOutcome(**payload)

    async def test_writes_final_response_and_completes_the_workflow(
        self, fake_agent_llm_factory
    ):
        llm = fake_agent_llm_factory(
            outcomes={ResponseOutcome: self.response_outcome()}
        )
        update = await make_response_agent_node(llm=llm)(initial_state())

        assert update["final_response"].startswith("Hi Alice")
        assert update["workflow_status"] == "completed"
        result = update["agent_results"][0]
        assert set(result) == AGENT_RESULT_KEYS
        assert result["output_data"]["internal_note"]

    async def test_reads_only_graphstate_no_tools_bound(
        self, fake_agent_llm_factory
    ):
        """SRS §34: Response Agent -> MCP is forbidden."""
        llm = fake_agent_llm_factory(
            outcomes={ResponseOutcome: self.response_outcome()}
        )
        await make_response_agent_node(llm=llm)(initial_state())
        assert llm.bound_tools == []

    async def test_agent_results_reach_the_prompt(self, fake_agent_llm_factory):
        llm = fake_agent_llm_factory(
            outcomes={ResponseOutcome: self.response_outcome()}
        )
        prior = {
            "agent_name": "policy_agent",
            "status": "success",
            "summary": "Approved.",
            "confidence": 0.98,
            "actions_taken": [],
            "tool_calls": [],
            "output_data": {"approved": True, "risk": "low"},
        }
        await make_response_agent_node(llm=llm)(initial_state(agent_results=[prior]))

        _, messages = llm.structured_calls[0]
        assert "policy_agent" in messages[-1].content

    async def test_generation_failure_fails_the_workflow(
        self, fake_agent_llm_factory
    ):
        llm = fake_agent_llm_factory(outcomes={})
        update = await make_response_agent_node(llm=llm)(initial_state())
        assert update["workflow_status"] == "failed"
        assert "final_response" not in update
        assert update["errors"]
