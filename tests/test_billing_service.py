"""Unit tests for BillingService (refund matrix, lookups)."""

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models import Invoice, Subscription, User
from app.models.enums import PaymentStatus, SubscriptionPlan
from app.services.billing_service import BillingService
from app.services.exceptions import (
    InvoiceNotFoundError,
    SubscriptionNotFoundError,
)


async def _make_user(session) -> User:
    user = User(
        company_name="Acme Corp",
        full_name="Alice Admin",
        email=f"{uuid.uuid4()}@acme.test",
    )
    session.add(user)
    await session.commit()
    return user


async def _make_invoice(session, user, status: PaymentStatus) -> Invoice:
    invoice = Invoice(
        user_id=user.id, amount=Decimal("199.99"), payment_status=status
    )
    session.add(invoice)
    await session.commit()
    return invoice


async def test_get_invoice(session_factory):
    async with session_factory() as session:
        user = await _make_user(session)
        invoice = await _make_invoice(session, user, PaymentStatus.PAID)

        found = await BillingService(session).get_invoice(invoice.id)
        assert found.id == invoice.id
        assert found.amount == Decimal("199.99")


async def test_get_invoice_missing(session_factory):
    async with session_factory() as session:
        with pytest.raises(InvoiceNotFoundError):
            await BillingService(session).get_invoice(uuid.uuid4())


async def test_get_subscription_returns_latest(session_factory):
    async with session_factory() as session:
        user = await _make_user(session)
        session.add(
            Subscription(
                user_id=user.id,
                plan=SubscriptionPlan.BASIC,
                monthly_price=Decimal("29.00"),
                renewal_date=date(2026, 1, 1),
            )
        )
        session.add(
            Subscription(
                user_id=user.id,
                plan=SubscriptionPlan.ENTERPRISE,
                monthly_price=Decimal("499.00"),
                renewal_date=date(2026, 12, 1),
            )
        )
        await session.commit()

        subscription = await BillingService(session).get_subscription(user.id)
        assert subscription.plan is SubscriptionPlan.ENTERPRISE


async def test_get_subscription_missing(session_factory):
    async with session_factory() as session:
        user = await _make_user(session)
        with pytest.raises(SubscriptionNotFoundError):
            await BillingService(session).get_subscription(user.id)


@pytest.mark.parametrize(
    ("status", "eligible", "amount"),
    [
        (PaymentStatus.DUPLICATE, True, Decimal("199.99")),
        (PaymentStatus.REFUNDED, False, Decimal("0")),
        (PaymentStatus.PENDING, False, Decimal("0")),
        (PaymentStatus.PAID, False, Decimal("0")),
    ],
)
async def test_calculate_refund_matrix(session_factory, status, eligible, amount):
    async with session_factory() as session:
        user = await _make_user(session)
        invoice = await _make_invoice(session, user, status)

        decision = await BillingService(session).calculate_refund(invoice.id)
        assert decision["eligible"] is eligible
        assert decision["refund_amount"] == amount
        assert decision["currency"] == "USD"
        assert decision["reason"]


async def test_calculate_refund_never_mutates_invoice(session_factory):
    async with session_factory() as session:
        user = await _make_user(session)
        invoice = await _make_invoice(session, user, PaymentStatus.DUPLICATE)

        await BillingService(session).calculate_refund(invoice.id)
        await session.refresh(invoice)
        assert invoice.payment_status is PaymentStatus.DUPLICATE
