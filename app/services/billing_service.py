"""Billing business logic backing the Enterprise MCP billing tools (SRS §31)."""

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Invoice, Subscription
from app.models.enums import PaymentStatus
from app.services.exceptions import (
    InvoiceNotFoundError,
    SubscriptionNotFoundError,
)

logger = logging.getLogger(__name__)


class BillingService:
    """Reads invoices/subscriptions and computes deterministic refund decisions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_invoice(self, invoice_id: uuid.UUID) -> Invoice:
        """Return an invoice by id."""
        invoice = await self._session.get(Invoice, invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError(str(invoice_id))
        return invoice

    async def get_subscription(self, customer_id: uuid.UUID) -> Subscription:
        """Return the customer's most recent subscription."""
        subscription = await self._session.scalar(
            select(Subscription)
            .where(Subscription.user_id == customer_id)
            .order_by(Subscription.renewal_date.desc())
            .limit(1)
        )
        if subscription is None:
            raise SubscriptionNotFoundError(str(customer_id))
        return subscription

    async def calculate_refund(self, invoice_id: uuid.UUID) -> dict:
        """Deterministically evaluate refund eligibility for an invoice.

        Read-only: never mutates the invoice. Only a duplicate charge is
        automatically eligible; everything else requires policy review or is
        already settled.
        """
        invoice = await self.get_invoice(invoice_id)

        if invoice.payment_status is PaymentStatus.DUPLICATE:
            eligible, refund_amount, reason = (
                True,
                invoice.amount,
                "Duplicate charge detected; full refund of the invoice amount.",
            )
        elif invoice.payment_status is PaymentStatus.REFUNDED:
            eligible, refund_amount, reason = (
                False,
                Decimal("0"),
                "Invoice has already been refunded.",
            )
        elif invoice.payment_status is PaymentStatus.PENDING:
            eligible, refund_amount, reason = (
                False,
                Decimal("0"),
                "Invoice has not been paid yet; nothing to refund.",
            )
        else:  # PaymentStatus.PAID
            eligible, refund_amount, reason = (
                False,
                Decimal("0"),
                "No duplicate charge detected; refund requires policy review.",
            )

        return {
            "invoice_id": str(invoice.id),
            "eligible": eligible,
            "refund_amount": refund_amount,
            "currency": invoice.currency,
            "reason": reason,
        }
