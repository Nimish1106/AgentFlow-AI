"""Pydantic result models returned by Enterprise MCP tools (SRS §31).

Every tool returns a JSON-serialisable dict produced from one of these models,
so agents receive a stable, typed payload regardless of namespace.
"""

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ToolError(BaseModel):
    """Structured error returned instead of raising across the MCP boundary."""

    model_config = ConfigDict(from_attributes=True)

    error: str
    code: str


class CustomerResult(BaseModel):
    """Customer account details (account namespace)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    company_name: str
    full_name: str
    email: str
    account_status: str
    role: str
    feature_flags: dict


class InvoiceResult(BaseModel):
    """Invoice details (billing namespace)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    amount: Decimal
    currency: str
    payment_status: str


class SubscriptionResult(BaseModel):
    """Subscription details (billing namespace)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    plan: str
    monthly_price: Decimal
    renewal_date: str
    subscription_status: str


class RefundCalculation(BaseModel):
    """Deterministic refund eligibility decision (billing namespace)."""

    model_config = ConfigDict(from_attributes=True)

    invoice_id: str
    eligible: bool
    refund_amount: Decimal
    currency: str
    reason: str


class TicketResult(BaseModel):
    """Support ticket details (ticket namespace)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    customer_id: str
    title: str
    description: str
    priority: str
    status: str


class NoteResult(BaseModel):
    """Internal ticket note (ticket namespace)."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    ticket_id: str
    author: str
    note: str


class KnowledgeSearchResult(BaseModel):
    """Knowledge search payload (knowledge namespace, RAG contract SRS §33)."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    query: str
    collection: str
    results: List[dict]
    message: Optional[str] = None
