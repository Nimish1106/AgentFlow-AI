"""Tests for HITL pause/resume and the delivery Dispatcher node (SRS §38, §14)."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.config.settings import Settings
from app.graph.constants import AgentName, Domain
from app.graph.nodes.dispatcher import CHANNEL_PORTAL, CHANNEL_WEBHOOK
from app.graph.nodes.dispatcher import CONTEXT_KEY as DISPATCH_KEY
from app.graph.nodes.dispatcher import NODE_NAME as DISPATCHER_NODE
from app.graph.nodes.dispatcher import dispatcher_node
from app.graph.nodes.hitl import (
    APPROVED,
    NODE_NAME as HITL_NODE,
    REJECTED,
    build_approval_request,
    parse_decision,
)
from app.graph.nodes.risk_engine import CONTEXT_KEY as RISK_KEY
from app.graph.nodes.supervisor import SupervisorClassification
from app.graph.state import AgentResult, build_initial_state
from app.graph.workflow import build_workflow_graph


def initial_state(**overrides):
    """Initial state for a canned billing ticket."""
    state = build_initial_state(
        workflow_id="wf_hitl_001",
        ticket_id="tkt_001",
        customer_id="cust_001",
        issue_text="I was charged twice for my subscription this month.",
        customer_tier="enterprise",
        ticket_priority="high",
    )
    state.update(overrides)
    return state


class TestDecisionParsing:
    def test_parses_a_bare_bool_resume(self):
        """SRS §38 documents Command(resume=True)."""
        assert parse_decision(True)["approved"] is True

    def test_parses_a_full_decision_mapping(self):
        decision = parse_decision(
            {
                "approved": True,
                "reviewer_name": "Support Manager",
                "comments": "Refund approved.",
            }
        )
        assert decision == {
            "approved": True,
            "reviewer_name": "Support Manager",
            "comments": "Refund approved.",
        }

    def test_mapping_without_approved_is_a_rejection(self):
        assert parse_decision({"reviewer_name": "Nobody"})["approved"] is False

    @pytest.mark.parametrize("value", [None, "yes", 42, []])
    def test_unreadable_decision_is_never_read_as_consent(self, value):
        assert parse_decision(value)["approved"] is False


class TestApprovalRequest:
    def test_describes_the_decision_for_the_reviewer(self):
        state = initial_state(
            risk_score=0.9,
            shared_context={
                RISK_KEY: {"risk_level": "high", "reasons": ["refund 5000 > 1000"]}
            },
            agent_results=[
                AgentResult(
                    agent_name=AgentName.BILLING.value,
                    status="success",
                    summary="Duplicate charge confirmed.",
                    confidence=0.95,
                    actions_taken=[],
                    tool_calls=[],
                    output_data={},
                )
            ],
        )
        request = build_approval_request(state)
        assert request["risk_level"] == "high"
        assert request["reasons"] == ["refund 5000 > 1000"]
        assert request["workflow_id"] == "wf_hitl_001"
        assert request["agent_summaries"][0]["agent_name"] == AgentName.BILLING.value

    def test_is_safe_when_the_risk_engine_left_no_record(self):
        request = build_approval_request(initial_state())
        assert request["risk_level"] == "unknown"
        assert request["agent_summaries"] == []


class TestDispatcherNode:
    @pytest.fixture
    def no_webhook(self, monkeypatch):
        import app.graph.nodes.dispatcher as dispatcher

        monkeypatch.setattr(
            dispatcher, "get_settings", lambda: Settings(dispatch_webhook_url="")
        )

    @pytest.fixture
    def webhook(self, monkeypatch):
        import app.graph.nodes.dispatcher as dispatcher

        monkeypatch.setattr(
            dispatcher,
            "get_settings",
            lambda: Settings(dispatch_webhook_url="https://hooks.test/agentflow"),
        )

    async def test_delivers_to_the_portal_and_completes(self, no_webhook):
        update = await dispatcher_node(
            initial_state(final_response="Your refund is on its way.")
        )
        assert update["workflow_status"] == "completed"
        assert update["shared_context"][DISPATCH_KEY]["delivered"] == [CHANNEL_PORTAL]
        assert update["current_node"] == DISPATCHER_NODE

    async def test_posts_to_the_configured_webhook(self, webhook, monkeypatch):
        import app.graph.nodes.dispatcher as dispatcher

        posted = {}

        async def fake_post(url, payload, timeout):
            posted.update({"url": url, "payload": payload, "timeout": timeout})

        monkeypatch.setattr(dispatcher, "_post_webhook", fake_post)

        update = await dispatcher_node(
            initial_state(final_response="Your refund is on its way.")
        )
        assert posted["url"] == "https://hooks.test/agentflow"
        assert posted["payload"]["response"] == "Your refund is on its way."
        assert posted["payload"]["workflow_id"] == "wf_hitl_001"
        assert update["shared_context"][DISPATCH_KEY]["delivered"] == [
            CHANNEL_PORTAL,
            CHANNEL_WEBHOOK,
        ]

    async def test_webhook_failure_logs_and_completes_anyway(
        self, webhook, monkeypatch
    ):
        """SRS §13 step 14: delivery failure must never crash the workflow."""
        import app.graph.nodes.dispatcher as dispatcher

        async def failing_post(url, payload, timeout):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(dispatcher, "_post_webhook", failing_post)

        update = await dispatcher_node(
            initial_state(final_response="Your refund is on its way.")
        )
        assert update["workflow_status"] == "completed"
        assert update["shared_context"][DISPATCH_KEY]["failed"] == [CHANNEL_WEBHOOK]
        assert "connection refused" in update["errors"][0]

    async def test_records_nothing_delivered_without_a_response(self, no_webhook):
        update = await dispatcher_node(initial_state(final_response=None))
        dispatch = update["shared_context"][DISPATCH_KEY]
        assert dispatch["delivered"] == []
        assert dispatch["response_delivered"] is False


class TestGraphInterruptAndResume:
    """SRS §38: the graph pauses at HITL and resumes from its checkpoint."""

    @pytest.fixture
    def full_llm(self, fake_agent_llm_factory):
        """One fake LLM serving every reasoning node, proposing a large refund."""
        from app.agents.schemas import AgentOutcome, PolicyOutcome, ResponseOutcome

        return fake_agent_llm_factory(
            outcomes={
                SupervisorClassification: SupervisorClassification(
                    intent="Duplicate Invoice Charge",
                    domains=[Domain.BILLING],
                    priority="high",
                ),
                AgentOutcome: AgentOutcome(
                    summary="Duplicate charge confirmed.",
                    confidence=0.95,
                    output_data={"refund_eligible": True, "refund_amount": 5000.0},
                ),
                PolicyOutcome: PolicyOutcome(
                    summary="Refund follows policy.",
                    confidence=0.95,
                    approved=True,
                    risk="low",
                ),
                ResponseOutcome: ResponseOutcome(
                    customer_response="Your refund is on its way.",
                    internal_note="Refund approved by reviewer.",
                    resolution_summary="Duplicate charge refunded.",
                    confidence=0.95,
                ),
            }
        )

    @pytest.fixture
    def graph(self, full_llm, fake_mcp_client_factory):
        """A graph with a shared checkpointer so a thread can be resumed."""
        return build_workflow_graph(
            llm=full_llm,
            mcp_client=fake_mcp_client_factory(),
            checkpointer=InMemorySaver(),
        )

    @pytest.fixture
    def config(self):
        return {"configurable": {"thread_id": "wf_hitl_001"}}

    async def test_high_risk_run_pauses_at_the_hitl_node(self, graph, config):
        result = await graph.ainvoke(initial_state(), config=config)

        assert result["__interrupt__"]
        assert result.get("final_response") is None
        state = await graph.aget_state(config)
        assert state.next == (HITL_NODE,)

    async def test_interrupt_payload_describes_the_decision(self, graph, config):
        result = await graph.ainvoke(initial_state(), config=config)

        payload = result["__interrupt__"][0].value
        assert payload["risk_level"] == "high"
        assert any("exceeds threshold" in r for r in payload["reasons"])

    async def test_approval_resumes_and_delivers_the_response(self, graph, config):
        await graph.ainvoke(initial_state(), config=config)

        resumed = await graph.ainvoke(
            Command(
                resume={
                    "approved": True,
                    "reviewer_name": "Support Manager",
                    "comments": "Refund approved.",
                }
            ),
            config=config,
        )

        assert resumed["approval_status"] == APPROVED
        assert resumed["final_response"] == "Your refund is on its way."
        assert resumed["workflow_status"] == "completed"
        assert resumed["shared_context"]["hitl"]["reviewer_name"] == "Support Manager"

    async def test_rejection_still_reaches_the_customer_response(
        self, graph, config
    ):
        """A rejected action is explained to the customer, not silently dropped."""
        await graph.ainvoke(initial_state(), config=config)

        resumed = await graph.ainvoke(
            Command(resume={"approved": False, "reviewer_name": "Manager"}),
            config=config,
        )

        assert resumed["approval_status"] == REJECTED
        assert resumed["final_response"]
        assert resumed["workflow_status"] == "completed"

    async def test_resume_continues_from_the_checkpoint_without_rerunning_agents(
        self, graph, config, full_llm
    ):
        """SRS §38: approval resumes a workflow, it never restarts one."""
        await graph.ainvoke(initial_state(), config=config)
        calls_before = len(full_llm.structured_calls)

        await graph.ainvoke(
            Command(resume={"approved": True, "reviewer_name": "Manager"}),
            config=config,
        )

        schemas_after = [
            schema for schema, _ in full_llm.structured_calls[calls_before:]
        ]
        from app.agents.schemas import ResponseOutcome

        # Only the Response Agent runs after the interrupt; the supervisor,
        # billing agent and policy agent are not re-invoked.
        assert schemas_after == [ResponseOutcome]

    async def test_low_risk_run_never_pauses(
        self, full_llm, fake_mcp_client_factory
    ):
        from app.agents.schemas import AgentOutcome

        full_llm.outcomes[AgentOutcome] = AgentOutcome(
            summary="Duplicate charge confirmed.",
            confidence=0.95,
            output_data={"refund_eligible": True, "refund_amount": 199.99},
        )
        graph = build_workflow_graph(
            llm=full_llm,
            mcp_client=fake_mcp_client_factory(),
            checkpointer=InMemorySaver(),
        )

        result = await graph.ainvoke(
            initial_state(), config={"configurable": {"thread_id": "wf_low_risk"}}
        )

        assert "__interrupt__" not in result
        assert result["requires_hitl"] is False
        assert result["workflow_status"] == "completed"
        assert result["approval_status"] is None
