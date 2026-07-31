"""Tests for GraphState reducers, the Supervisor node, and the base graph (SRS §21, §37)."""

import operator
import typing

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from app.graph.constants import AgentName, Domain
from app.graph.nodes.aggregator import NODE_NAME as AGGREGATOR_NODE
from app.graph.nodes.dispatcher import NODE_NAME as DISPATCHER_NODE
from app.graph.nodes.hitl import NODE_NAME as HITL_NODE
from app.graph.nodes.planner import NODE_NAME as PLANNER_NODE
from app.graph.nodes.risk_engine import NODE_NAME as RISK_NODE
from app.graph.nodes.supervisor import (
    NODE_NAME as SUPERVISOR_NODE,
)
from app.graph.nodes.supervisor import (
    SupervisorClassification,
    make_supervisor_node,
)
from app.graph.state import AgentResult, GraphState, build_initial_state
from app.graph.workflow import (
    build_workflow_graph,
    route_after_planner,
    route_after_policy,
    route_after_response,
    route_after_risk,
    route_after_supervisor,
)


def make_agent_result(name: str) -> AgentResult:
    """Build a minimal valid AgentResult."""
    return AgentResult(
        agent_name=name,
        status="success",
        summary=f"{name} done",
        confidence=0.9,
        actions_taken=[],
        tool_calls=[],
        output_data={},
    )


def initial_state(**overrides) -> GraphState:
    """Initial state for a canned billing ticket."""
    state = build_initial_state(
        workflow_id="wf_test_001",
        ticket_id="tkt_001",
        customer_id="cust_001",
        issue_text="I was charged twice for my subscription this month.",
        customer_tier="enterprise",
        ticket_priority="high",
    )
    state.update(overrides)
    return state


class TestStateContracts:
    def test_initial_state_populates_every_graphstate_key(self):
        """Nodes read arbitrary fields, so no key may be missing at start."""
        assert set(initial_state()) == set(typing.get_type_hints(GraphState))

    def test_agent_results_uses_operator_add_reducer(self):
        hints = typing.get_type_hints(GraphState, include_extras=True)
        assert operator.add in typing.get_args(hints["agent_results"])[1:]

    def test_errors_uses_operator_add_reducer(self):
        hints = typing.get_type_hints(GraphState, include_extras=True)
        assert operator.add in typing.get_args(hints["errors"])[1:]

    def test_messages_has_a_reducer(self):
        hints = typing.get_type_hints(GraphState, include_extras=True)
        metadata = typing.get_args(hints["messages"])[1:]
        assert metadata, "messages must carry the add_messages reducer"


class TestReducersUnderConcurrency:
    """Parallel branches must append to reduced fields, not clobber them."""

    @pytest.fixture
    def fan_out_graph(self):
        """Two concurrent nodes, each writing only reduced fields."""

        async def branch_a(state: GraphState):
            return {
                "agent_results": [make_agent_result(AgentName.BILLING.value)],
                "errors": ["billing: soft warning"],
            }

        async def branch_b(state: GraphState):
            return {
                "agent_results": [make_agent_result(AgentName.ACCOUNT.value)],
                "errors": ["account: soft warning"],
            }

        graph = StateGraph(GraphState)
        graph.add_node("branch_a", branch_a)
        graph.add_node("branch_b", branch_b)
        graph.add_edge(START, "branch_a")
        graph.add_edge(START, "branch_b")
        graph.add_edge("branch_a", END)
        graph.add_edge("branch_b", END)
        return graph.compile()

    async def test_parallel_agent_results_are_both_kept(self, fan_out_graph):
        result = await fan_out_graph.ainvoke(initial_state())
        names = sorted(r["agent_name"] for r in result["agent_results"])
        assert names == [AgentName.ACCOUNT.value, AgentName.BILLING.value]

    async def test_parallel_errors_are_both_kept(self, fan_out_graph):
        result = await fan_out_graph.ainvoke(initial_state())
        assert len(result["errors"]) == 2

    async def test_reducer_appends_to_preexisting_values(self, fan_out_graph):
        """operator.add extends what is already in state rather than replacing it."""
        seeded = initial_state(
            agent_results=[make_agent_result("seed_agent")],
            errors=["seed: earlier failure"],
        )
        result = await fan_out_graph.ainvoke(seeded)
        assert len(result["agent_results"]) == 3
        assert result["agent_results"][0]["agent_name"] == "seed_agent"
        assert len(result["errors"]) == 3

    async def test_unreduced_field_is_overwritten_not_appended(self):
        """Sanity check the reducer is what makes the difference, not LangGraph itself."""

        async def node(state: GraphState):
            return {"current_node": "second"}

        graph = StateGraph(GraphState)
        graph.add_node("node", node)
        graph.add_edge(START, "node")
        graph.add_edge("node", END)
        result = await graph.compile().ainvoke(initial_state(current_node="first"))
        assert result["current_node"] == "second"


class TestSupervisorNode:
    def classification(self, **overrides) -> SupervisorClassification:
        payload = {
            "intent": "Duplicate Invoice Charge",
            "domains": [Domain.BILLING, Domain.ACCOUNT],
            "priority": "high",
        }
        payload.update(overrides)
        return SupervisorClassification(**payload)

    async def test_writes_classification_into_shared_context(self, fake_llm_factory):
        node = make_supervisor_node(fake_llm_factory(result=self.classification()))
        update = await node(initial_state())
        assert update["shared_context"]["intent"] == "Duplicate Invoice Charge"
        assert update["shared_context"]["domains"] == ["billing", "account"]
        assert update["shared_context"]["priority"] == "high"

    async def test_returns_only_its_own_shared_context_contribution(
        self, fake_llm_factory
    ):
        """shared_context carries a merge reducer: nodes return only their own
        keys and LangGraph merges, so parallel writers cannot clobber."""
        node = make_supervisor_node(fake_llm_factory(result=self.classification()))
        update = await node(initial_state(shared_context={"customer_name": "Alice"}))
        assert "customer_name" not in update["shared_context"]
        assert set(update["shared_context"]) == {"intent", "domains", "priority"}

    async def test_records_itself_as_completed_and_emits_a_message(
        self, fake_llm_factory
    ):
        node = make_supervisor_node(fake_llm_factory(result=self.classification()))
        update = await node(initial_state())
        assert AgentName.SUPERVISOR.value in update["completed_agents"]
        assert isinstance(update["messages"][0], AIMessage)

    async def test_sets_running_status_and_current_node(self, fake_llm_factory):
        node = make_supervisor_node(fake_llm_factory(result=self.classification()))
        update = await node(initial_state())
        assert update["workflow_status"] == "running"
        assert update["current_node"] == SUPERVISOR_NODE

    async def test_prompt_includes_the_ticket_text(self, fake_llm_factory):
        llm = fake_llm_factory(result=self.classification())
        await make_supervisor_node(llm)(initial_state())
        human = [m for m in llm.calls[0] if isinstance(m, HumanMessage)][0]
        assert "charged twice" in human.content

    async def test_supervisor_does_not_build_the_plan(self, fake_llm_factory):
        """Planning belongs to the deterministic planner, not the LLM node."""
        node = make_supervisor_node(fake_llm_factory(result=self.classification()))
        update = await node(initial_state())
        assert "execution_plan" not in update

    async def test_llm_failure_fails_the_workflow_and_records_the_error(
        self, fake_llm_factory
    ):
        node = make_supervisor_node(
            fake_llm_factory(raises=RuntimeError("groq unavailable"))
        )
        update = await node(initial_state())
        assert update["workflow_status"] == "failed"
        assert "groq unavailable" in update["errors"][0]

    async def test_llm_failure_returns_errors_as_a_list_for_the_reducer(
        self, fake_llm_factory
    ):
        node = make_supervisor_node(fake_llm_factory(raises=RuntimeError("boom")))
        update = await node(initial_state())
        assert isinstance(update["errors"], list)


class TestDefaultSupervisorNode:
    async def test_default_node_uses_the_configured_llm(
        self, monkeypatch, fake_llm_factory
    ):
        """The graph's default node resolves the Groq model lazily at invocation."""
        from app.graph import llm as llm_module
        from app.graph.nodes.supervisor import supervisor_node

        llm = fake_llm_factory(
            result=SupervisorClassification(
                intent="Duplicate Invoice Charge",
                domains=[Domain.BILLING],
                priority="high",
            )
        )
        monkeypatch.setattr(llm_module, "get_llm", lambda: llm)

        update = await supervisor_node(initial_state())
        assert update["shared_context"]["domains"] == ["billing"]


class TestLLMFactory:
    """The Groq factory is the only place credentials are read (SRS §46)."""

    def build(self, monkeypatch, **settings_overrides):
        from app.config.settings import Settings
        from app.graph import llm as llm_module

        llm_module.get_llm.cache_clear()
        monkeypatch.setattr(
            llm_module, "get_settings", lambda: Settings(**settings_overrides)
        )
        try:
            return llm_module.get_llm()
        finally:
            llm_module.get_llm.cache_clear()

    def test_missing_api_key_raises_a_clear_error(self, monkeypatch):
        from app.graph.llm import LLMNotConfiguredError

        with pytest.raises(LLMNotConfiguredError, match="GROQ_API_KEY"):
            self.build(monkeypatch, groq_api_key="")

    def test_configured_key_builds_a_model_with_the_configured_settings(
        self, monkeypatch
    ):
        llm = self.build(
            monkeypatch,
            groq_api_key="test-key",
            groq_model="llama-3.1-8b-instant",
            llm_temperature=0.0,
        )
        assert llm.model_name == "llama-3.1-8b-instant"
        # ChatGroq clamps an exact 0.0 to a tiny epsilon, which the Groq API accepts.
        assert llm.temperature == pytest.approx(0.0, abs=1e-6)


class TestRouting:
    def test_failed_supervisor_routes_to_end(self):
        assert route_after_supervisor(initial_state(workflow_status="failed")) == END

    def test_successful_supervisor_routes_to_planner(self):
        state = initial_state(workflow_status="running")
        assert route_after_supervisor(state) == PLANNER_NODE

    def _plan_for(self, *agents: str):
        return [
            {
                "task_id": f"task_{i}",
                "task_name": agent,
                "assigned_agent": agent,
                "priority": "medium",
                "depends_on": [],
                "status": "pending",
            }
            for i, agent in enumerate(agents, start=1)
        ]

    def test_planner_fans_out_to_every_planned_domain_agent(self):
        state = initial_state(
            execution_plan=self._plan_for(
                AgentName.BILLING.value,
                AgentName.TECHNICAL.value,
                AgentName.POLICY.value,
                AgentName.RESPONSE.value,
            )
        )
        assert route_after_planner(state) == [
            AgentName.BILLING.value,
            AgentName.TECHNICAL.value,
        ]

    def test_planner_with_no_domain_tasks_routes_to_policy(self):
        state = initial_state(
            execution_plan=self._plan_for(
                AgentName.POLICY.value, AgentName.RESPONSE.value
            )
        )
        assert route_after_planner(state) == [AgentName.POLICY.value]

    def test_failed_policy_routes_to_end(self):
        assert route_after_policy(initial_state(workflow_status="failed")) == END

    def test_successful_policy_routes_to_the_aggregator(self):
        state = initial_state(workflow_status="running")
        assert route_after_policy(state) == AGGREGATOR_NODE

    def test_risk_requiring_hitl_routes_to_human_approval(self):
        assert route_after_risk(initial_state(requires_hitl=True)) == HITL_NODE

    def test_low_risk_skips_human_approval(self):
        state = initial_state(requires_hitl=False)
        assert route_after_risk(state) == AgentName.RESPONSE.value

    def test_response_routes_to_the_dispatcher(self):
        state = initial_state(workflow_status="running")
        assert route_after_response(state) == DISPATCHER_NODE

    def test_failed_response_skips_delivery(self):
        assert route_after_response(initial_state(workflow_status="failed")) == END


class TestBaseGraph:
    @pytest.fixture
    def full_llm(self, fake_agent_llm_factory):
        """One fake LLM serving every reasoning node in a full run."""
        from app.agents.schemas import AgentOutcome, PolicyOutcome, ResponseOutcome

        return fake_agent_llm_factory(
            outcomes={
                SupervisorClassification: SupervisorClassification(
                    intent="Duplicate Invoice Charge",
                    domains=[Domain.BILLING, Domain.ACCOUNT],
                    priority="high",
                ),
                AgentOutcome: AgentOutcome(
                    summary="Checked.", confidence=0.9, output_data={}
                ),
                PolicyOutcome: PolicyOutcome(
                    summary="Approved.",
                    confidence=0.98,
                    approved=True,
                    risk="low",
                ),
                ResponseOutcome: ResponseOutcome(
                    customer_response="Your refund is on its way.",
                    internal_note="Refund approved.",
                    resolution_summary="Duplicate charge refunded.",
                    confidence=0.95,
                ),
            }
        )

    def build(self, llm, fake_mcp_client_factory):
        return build_workflow_graph(llm=llm, mcp_client=fake_mcp_client_factory())

    def test_graph_compiles_without_an_api_key(self):
        """Compilation must not require Groq credentials - the LLM resolves lazily."""
        assert build_workflow_graph() is not None

    def test_compiled_graph_exposes_every_agent_node(self):
        nodes = build_workflow_graph().get_graph().nodes
        assert SUPERVISOR_NODE in nodes
        assert PLANNER_NODE in nodes
        for agent in (
            AgentName.BILLING,
            AgentName.ACCOUNT,
            AgentName.TECHNICAL,
            AgentName.POLICY,
            AgentName.RESPONSE,
        ):
            assert agent.value in nodes

    def test_compiled_graph_exposes_every_governance_node(self):
        """SRS §37: aggregator, risk engine, HITL and dispatcher are all nodes."""
        nodes = build_workflow_graph().get_graph().nodes
        for node in (AGGREGATOR_NODE, RISK_NODE, HITL_NODE, DISPATCHER_NODE):
            assert node in nodes

    async def test_end_to_end_run_produces_an_execution_plan(
        self, full_llm, fake_mcp_client_factory
    ):
        graph = self.build(full_llm, fake_mcp_client_factory)
        config = {"configurable": {"thread_id": "wf_test_001"}}

        result = await graph.ainvoke(initial_state(), config=config)

        assert [t["assigned_agent"] for t in result["execution_plan"]] == [
            AgentName.BILLING.value,
            AgentName.ACCOUNT.value,
            AgentName.POLICY.value,
            AgentName.RESPONSE.value,
        ]
        assert result["errors"] == []

    async def test_end_to_end_run_executes_planned_agents_and_responds(
        self, full_llm, fake_mcp_client_factory
    ):
        """SRS §37: plan-driven fan-out, policy gate, then the final response."""
        graph = self.build(full_llm, fake_mcp_client_factory)
        result = await graph.ainvoke(
            initial_state(), config={"configurable": {"thread_id": "wf_full"}}
        )

        result_names = [r["agent_name"] for r in result["agent_results"]]
        assert sorted(result_names[:2]) == [
            AgentName.ACCOUNT.value,
            AgentName.BILLING.value,
        ]
        assert result_names[2:] == [
            AgentName.POLICY.value,
            AgentName.RESPONSE.value,
        ]
        assert AgentName.TECHNICAL.value not in result_names
        assert result["final_response"] == "Your refund is on its way."
        assert result["workflow_status"] == "completed"
        assert result["risk_score"] == 0.2

    async def test_end_to_end_run_with_no_domains_still_runs_policy_and_response(
        self, full_llm, fake_mcp_client_factory
    ):
        from app.agents.schemas import PolicyOutcome  # noqa: F401 - clarity

        full_llm.outcomes[SupervisorClassification] = SupervisorClassification(
            intent="General Enquiry", domains=[], priority="low"
        )
        graph = self.build(full_llm, fake_mcp_client_factory)
        result = await graph.ainvoke(
            initial_state(), config={"configurable": {"thread_id": "wf_test_002"}}
        )
        assert [r["agent_name"] for r in result["agent_results"]] == [
            AgentName.POLICY.value,
            AgentName.RESPONSE.value,
        ]
        assert result["workflow_status"] == "completed"

    async def test_supervisor_failure_short_circuits_before_planning(
        self, fake_llm_factory
    ):
        graph = build_workflow_graph(
            llm=fake_llm_factory(raises=RuntimeError("groq unavailable"))
        )
        result = await graph.ainvoke(
            initial_state(), config={"configurable": {"thread_id": "wf_test_003"}}
        )
        assert result["workflow_status"] == "failed"
        assert result["execution_plan"] == []
        assert result.get("final_response") is None

    async def test_policy_failure_stops_before_the_response(
        self, full_llm, fake_mcp_client_factory
    ):
        """SRS §35: no policy verdict means no customer-facing reply."""
        from app.agents.schemas import PolicyOutcome

        del full_llm.outcomes[PolicyOutcome]  # policy node now raises
        graph = self.build(full_llm, fake_mcp_client_factory)
        result = await graph.ainvoke(
            initial_state(), config={"configurable": {"thread_id": "wf_pol_fail"}}
        )
        assert result["workflow_status"] == "failed"
        assert result.get("final_response") is None

    async def test_state_is_checkpointed_after_every_node(
        self, full_llm, fake_mcp_client_factory
    ):
        """SRS §46: each node checkpoints so the run is resumable."""
        graph = self.build(full_llm, fake_mcp_client_factory)
        config = {"configurable": {"thread_id": "wf_test_004"}}
        await graph.ainvoke(initial_state(), config=config)

        checkpointed = [step.next for step in graph.get_state_history(config)]
        assert len(checkpointed) > 1
        saved = await graph.aget_state(config)
        assert saved.values["execution_plan"]
        assert saved.values["final_response"]

    async def test_thread_id_isolates_separate_workflows(
        self, full_llm, fake_mcp_client_factory
    ):
        """HITL resumes by workflow_id as thread_id (SRS §38) - threads must not bleed."""
        graph = self.build(full_llm, fake_mcp_client_factory)
        await graph.ainvoke(
            initial_state(), config={"configurable": {"thread_id": "wf_a"}}
        )
        other = await graph.aget_state({"configurable": {"thread_id": "wf_b"}})
        assert other.values == {}
