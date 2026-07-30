"""Structured LLM outcome models for the Phase 4 agents (SRS §23, §30).

Each agent finishes its reasoning by emitting one of these via
``with_structured_output``; the node then maps it onto the uniform
``AgentResult`` contract that the Results Aggregator consumes.
"""

from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentOutcome(BaseModel):
    """Common closing summary a domain agent produces after its tool loop."""

    model_config = ConfigDict(from_attributes=True)

    summary: str = Field(description="One-paragraph summary of findings.")
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in the findings, 0.0-1.0."
    )
    actions_taken: List[str] = Field(
        default_factory=list,
        description="Short past-tense labels of the checks/actions performed.",
    )
    output_data: Dict = Field(
        default_factory=dict,
        description="Structured facts discovered (ids, statuses, amounts).",
    )


class PolicyOutcome(AgentOutcome):
    """Policy Agent verdict (SRS §30.6): approval decision plus risk level."""

    approved: bool = Field(description="Whether the proposed actions comply.")
    risk: Literal["low", "medium", "high"] = Field(
        description="Overall workflow risk level (SRS §27)."
    )


class ResponseOutcome(BaseModel):
    """Response Agent output (SRS §30.7)."""

    model_config = ConfigDict(from_attributes=True)

    customer_response: str = Field(
        description="Final reply to send to the customer."
    )
    internal_note: str = Field(
        description="Internal note for the support team."
    )
    resolution_summary: str = Field(
        description="One-sentence summary of how the ticket was resolved."
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in the response, 0.0-1.0."
    )
