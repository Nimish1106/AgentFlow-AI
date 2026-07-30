"""Canonical domain and agent names shared by the Supervisor and Task Planner."""

import enum


class Domain(str, enum.Enum):
    """Business domains the Supervisor may assign to a ticket (SRS §30.1)."""

    BILLING = "billing"
    ACCOUNT = "account"
    TECHNICAL = "technical"


class AgentName(str, enum.Enum):
    """Agent identifiers used in ExecutionTask.assigned_agent and AgentResult."""

    SUPERVISOR = "supervisor_agent"
    BILLING = "billing_agent"
    ACCOUNT = "account_agent"
    TECHNICAL = "technical_agent"
    POLICY = "policy_agent"
    RESPONSE = "response_agent"


#: Order domain tasks are emitted in, so an identical domain set always yields an
#: identical plan regardless of the order the Supervisor listed them.
DOMAIN_ORDER: tuple[Domain, ...] = (
    Domain.BILLING,
    Domain.ACCOUNT,
    Domain.TECHNICAL,
)
