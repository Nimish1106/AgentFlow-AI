"""Tests for the deterministic Task Planner (SRS §22, §30.2)."""

from app.graph.constants import AgentName
from app.graph.planner import (
    build_execution_plan,
    normalize_domains,
    normalize_priority,
)


def agents_of(plan):
    """Return the agent sequence of a plan."""
    return [task["assigned_agent"] for task in plan]


def task_by_agent(plan, agent: AgentName):
    """Return the single task assigned to `agent`."""
    matches = [t for t in plan if t["assigned_agent"] == agent.value]
    assert len(matches) == 1, f"expected exactly one {agent.value} task"
    return matches[0]


class TestPriorityNormalization:
    def test_known_priorities_pass_through(self):
        assert normalize_priority("low") == "low"
        assert normalize_priority("medium") == "medium"
        assert normalize_priority("high") == "high"

    def test_critical_collapses_to_high(self):
        # ExecutionTask.priority allows only low/medium/high (SRS §21).
        assert normalize_priority("critical") == "high"

    def test_case_and_whitespace_insensitive(self):
        assert normalize_priority("  HIGH  ") == "high"

    def test_unknown_and_empty_default_to_medium(self):
        assert normalize_priority("urgent") == "medium"
        assert normalize_priority("") == "medium"
        assert normalize_priority(None) == "medium"


class TestDomainNormalization:
    def test_canonical_order_is_independent_of_input_order(self):
        assert normalize_domains(["technical", "billing", "account"]) == (
            normalize_domains(["account", "technical", "billing"])
        )

    def test_duplicates_removed(self):
        assert len(normalize_domains(["billing", "billing", "BILLING"])) == 1

    def test_unknown_domains_dropped(self):
        result = [d.value for d in normalize_domains(["billing", "legal", "hr"])]
        assert result == ["billing"]

    def test_non_string_entries_dropped(self):
        result = [d.value for d in normalize_domains(["billing", None, 42])]
        assert result == ["billing"]

    def test_empty_input(self):
        assert normalize_domains([]) == []
        assert normalize_domains(None) == []


class TestExecutionPlan:
    def test_full_domain_plan_sequence(self):
        plan = build_execution_plan(
            {"domains": ["billing", "account", "technical"], "priority": "high"}
        )
        assert agents_of(plan) == [
            AgentName.BILLING.value,
            AgentName.ACCOUNT.value,
            AgentName.TECHNICAL.value,
            AgentName.POLICY.value,
            AgentName.RESPONSE.value,
        ]

    def test_policy_and_response_always_present(self):
        plan = build_execution_plan({"domains": [], "priority": "low"})
        assert agents_of(plan) == [
            AgentName.POLICY.value,
            AgentName.RESPONSE.value,
        ]

    def test_response_agent_is_always_last(self):
        for domains in ([], ["billing"], ["billing", "account", "technical"]):
            plan = build_execution_plan({"domains": domains, "priority": "medium"})
            assert plan[-1]["assigned_agent"] == AgentName.RESPONSE.value

    def test_domain_tasks_are_independent_so_they_can_run_in_parallel(self):
        plan = build_execution_plan(
            {"domains": ["billing", "account"], "priority": "medium"}
        )
        domain_tasks = [
            t
            for t in plan
            if t["assigned_agent"]
            in {AgentName.BILLING.value, AgentName.ACCOUNT.value}
        ]
        assert all(task["depends_on"] == [] for task in domain_tasks)

    def test_policy_depends_on_every_domain_task(self):
        plan = build_execution_plan(
            {"domains": ["billing", "technical"], "priority": "medium"}
        )
        domain_ids = [
            t["task_id"]
            for t in plan
            if t["assigned_agent"]
            in {AgentName.BILLING.value, AgentName.TECHNICAL.value}
        ]
        policy = task_by_agent(plan, AgentName.POLICY)
        assert policy["depends_on"] == domain_ids

    def test_response_depends_on_policy(self):
        plan = build_execution_plan({"domains": ["billing"], "priority": "medium"})
        policy = task_by_agent(plan, AgentName.POLICY)
        response = task_by_agent(plan, AgentName.RESPONSE)
        assert response["depends_on"] == [policy["task_id"]]

    def test_task_ids_are_unique_and_sequential(self):
        plan = build_execution_plan(
            {"domains": ["billing", "account", "technical"], "priority": "medium"}
        )
        ids = [task["task_id"] for task in plan]
        assert ids == [f"task_{i}" for i in range(1, len(plan) + 1)]
        assert len(set(ids)) == len(ids)

    def test_every_task_starts_pending(self):
        plan = build_execution_plan({"domains": ["billing"], "priority": "high"})
        assert all(task["status"] == "pending" for task in plan)

    def test_priority_applied_to_every_task(self):
        plan = build_execution_plan({"domains": ["billing"], "priority": "critical"})
        assert all(task["priority"] == "high" for task in plan)

    def test_dependencies_reference_existing_tasks(self):
        plan = build_execution_plan(
            {"domains": ["billing", "account", "technical"], "priority": "medium"}
        )
        known = {task["task_id"] for task in plan}
        for task in plan:
            assert set(task["depends_on"]) <= known

    def test_dependencies_only_point_backwards(self):
        """A task may only depend on tasks emitted before it - no cycles."""
        plan = build_execution_plan(
            {"domains": ["billing", "account", "technical"], "priority": "medium"}
        )
        seen: set[str] = set()
        for task in plan:
            assert set(task["depends_on"]) <= seen
            seen.add(task["task_id"])

    def test_plan_is_deterministic_across_calls(self):
        payload = {"domains": ["billing", "account"], "priority": "high"}
        assert build_execution_plan(payload) == build_execution_plan(payload)

    def test_plan_is_independent_of_domain_ordering(self):
        a = build_execution_plan({"domains": ["technical", "billing"], "priority": "low"})
        b = build_execution_plan({"domains": ["billing", "technical"], "priority": "low"})
        assert a == b

    def test_unknown_domain_does_not_abort_planning(self):
        plan = build_execution_plan({"domains": ["legal"], "priority": "medium"})
        assert agents_of(plan) == [
            AgentName.POLICY.value,
            AgentName.RESPONSE.value,
        ]

    def test_missing_keys_fall_back_to_defaults(self):
        plan = build_execution_plan({})
        assert agents_of(plan) == [
            AgentName.POLICY.value,
            AgentName.RESPONSE.value,
        ]
        assert all(task["priority"] == "medium" for task in plan)

    def test_planner_does_not_mutate_its_input(self):
        payload = {"domains": ["billing"], "priority": "high"}
        build_execution_plan(payload)
        assert payload == {"domains": ["billing"], "priority": "high"}
