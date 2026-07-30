"""Billing ORM models: subscriptions and invoices (SRS §18.2, §18.3)."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.models.enums import (
    PaymentStatus,
    SubscriptionPlan,
    SubscriptionStatus,
    as_db_enum,
)


class Subscription(Base):
    """SaaS subscription owned by a user."""

    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), index=True, nullable=False
    )
    plan: Mapped[SubscriptionPlan] = mapped_column(
        as_db_enum(SubscriptionPlan, "subscription_plan"), nullable=False
    )
    monthly_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    renewal_date: Mapped[date] = mapped_column(Date, nullable=False)
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        as_db_enum(SubscriptionStatus, "subscription_status"),
        default=SubscriptionStatus.ACTIVE,
        nullable=False,
    )


class Invoice(Base):
    """Billing history entry for a user."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), index=True, nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    payment_status: Mapped[PaymentStatus] = mapped_column(
        as_db_enum(PaymentStatus, "payment_status"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
