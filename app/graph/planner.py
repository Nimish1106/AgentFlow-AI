"""Deterministic Task Planner (SRS §22, §30.2).

Converts the Supervisor's intent breakdown into an ordered ``ExecutionTask`` list.

This component is plain Python by mandate: no LLM, no MCP, no I/O. The same
Supervisor output must always produce byte-identical plans, which is what makes a
workflow reproducible from its checkpoint.

Plan shape (SRS §37):
    domain agents (billing / account / technical, optional, mutually independent)
        -> policy agent (always)
        -> response agent (always last)
"""

import logging
from typing import Dict, Iterable, List

from app.graph.constants import DOMAIN_ORDER, AgentName, Domain
from app.graph.state import ExecutionTask, TaskPriority

logger = logging.getLogger(__name__)

#: Domain -> (agent, human-readable task name).
_DOMAIN_TASKS: Dict[Domain, tuple[AgentName, str]] = {
    Domain.BILLING: (AgentName.BILLING, "Verify Invoice"),
    Domain.ACCOUNT: (AgentName.ACCOUNT, "Verify Account"),
    Domain.TECHNICAL: (AgentName.TECHNICAL, "Diagnose Technical Issue"),
}

#: ExecutionTask.priority is low/medium/high (SRS §21) while ticket priority also
#: allows "critical" (SRS §27); collapse the extra level onto "high".
_PRIORITY_MAP: Dict[str, TaskPriority] = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "critical": "high",
}

_DEFAULT_PRIORITY: TaskPriority = "medium"


def normalize_priority(priority: str | None) -> TaskPriority:
    """Map a ticket/Supervisor priority onto the three ExecutionTask levels."""
    if not priority:
        return _DEFAULT_PRIORITY
    return _PRIORITY_MAP.get(priority.strip().lower(), _DEFAULT_PRIORITY)


def normalize_domains(domains: Iterable[str] | None) -> List[Domain]:
    """Deduplicate and canonically order raw domain strings from the Supervisor.

    Unrecognised domains are dropped with a warning rather than raising: an LLM
    naming a domain we do not implement should not abort the workflow, and the
    Policy and Response tasks alone are still a valid plan.
    """
    if not domains:
        return []

    selected: set[Domain] = set()
    for raw in domains:
        if not isinstance(raw, str):
            logger.warning("planner: ignoring non-string domain %r", raw)
            continue
        try:
            selected.add(Domain(raw.strip().lower()))
        except ValueError:
            logger.warning("planner: ignoring unknown domain %r", raw)

    return [domain for domain in DOMAIN_ORDER if domain in selected]


def build_execution_plan(supervisor_output: Dict) -> List[ExecutionTask]:
    """Turn Supervisor output into an ordered execution plan.

    Args:
        supervisor_output: Mapping with ``domains`` (list of domain names) and
            ``priority``. Extra keys such as ``intent`` are ignored here - they
            live in shared_context for the agents to read.

    Returns:
        Ordered ``ExecutionTask`` list. Domain tasks carry no dependencies so
        LangGraph may fan them out in parallel; the policy task depends on all of
        them, and the response task depends on policy.
    """
    domains = normalize_domains(supervisor_output.get("domains"))
    priority = normalize_priority(supervisor_output.get("priority"))

    tasks: List[ExecutionTask] = []

    def _next_id() -> str:
        return f"task_{len(tasks) + 1}"

    domain_task_ids: List[str] = []
    for domain in domains:
        agent, task_name = _DOMAIN_TASKS[domain]
        task_id = _next_id()
        domain_task_ids.append(task_id)
        tasks.append(
            ExecutionTask(
                task_id=task_id,
                task_name=task_name,
                assigned_agent=agent.value,
                priority=priority,
                depends_on=[],
                status="pending",
            )
        )

    # Policy always runs and gates the response (SRS §37).
    policy_task_id = _next_id()
    tasks.append(
        ExecutionTask(
            task_id=policy_task_id,
            task_name="Validate Policy Compliance",
            assigned_agent=AgentName.POLICY.value,
            priority=priority,
            depends_on=list(domain_task_ids),
            status="pending",
        )
    )

    tasks.append(
        ExecutionTask(
            task_id=_next_id(),
            task_name="Generate Response",
            assigned_agent=AgentName.RESPONSE.value,
            priority=priority,
            depends_on=[policy_task_id],
            status="pending",
        )
    )

    return tasks
