"""Seed the database with mock B2B SaaS data (SRS §4: Database Seeding).

Run after migrations:  python -m scripts.seed_database
Idempotent: skips seeding when users already exist.
"""

import asyncio
import logging
import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from faker import Faker
from sqlalchemy import func, select

from app.database.session import async_session_factory, engine
from app.models import Invoice, Subscription, User
from app.models.enums import (
    AccountStatus,
    PaymentStatus,
    SubscriptionPlan,
    SubscriptionStatus,
    UserRole,
)
from app.observability.logging import configure_logging

logger = logging.getLogger(__name__)

NUM_COMPANIES = 20

PLAN_PRICES = {
    SubscriptionPlan.BASIC: Decimal("49.00"),
    SubscriptionPlan.PREMIUM: Decimal("199.00"),
    SubscriptionPlan.ENTERPRISE: Decimal("499.00"),
}


def _build_company(fake: Faker) -> tuple[User, Subscription, list[Invoice]]:
    """Create one user with a subscription and invoice history."""
    user = User(
        id=uuid.uuid4(),
        company_name=fake.company(),
        full_name=fake.name(),
        email=fake.unique.company_email(),
        # Some locked accounts so later phases can exercise unlock flows.
        account_status=random.choices(
            [AccountStatus.ACTIVE, AccountStatus.LOCKED, AccountStatus.SUSPENDED],
            weights=[80, 15, 5],
        )[0],
        role=random.choice([UserRole.ADMIN, UserRole.MEMBER]),
    )

    plan = random.choice(list(SubscriptionPlan))
    subscription = Subscription(
        user_id=user.id,
        plan=plan,
        monthly_price=PLAN_PRICES[plan],
        renewal_date=date.today() + timedelta(days=random.randint(5, 360)),
        subscription_status=random.choices(
            [
                SubscriptionStatus.ACTIVE,
                SubscriptionStatus.CANCELLED,
                SubscriptionStatus.EXPIRED,
            ],
            weights=[85, 10, 5],
        )[0],
    )

    invoices = [
        Invoice(
            user_id=user.id,
            amount=PLAN_PRICES[plan],
            currency="USD",
            payment_status=PaymentStatus.PAID,
        )
        for _ in range(random.randint(2, 5))
    ]
    # Some duplicate charges so billing scenarios have data to find.
    if random.random() < 0.25:
        invoices.append(
            Invoice(
                user_id=user.id,
                amount=PLAN_PRICES[plan],
                currency="USD",
                payment_status=PaymentStatus.DUPLICATE,
            )
        )
    if random.random() < 0.2:
        invoices.append(
            Invoice(
                user_id=user.id,
                amount=PLAN_PRICES[plan],
                currency="USD",
                payment_status=PaymentStatus.PENDING,
            )
        )
    return user, subscription, invoices


async def seed() -> None:
    """Populate users, subscriptions, and invoices unless data already exists."""
    fake = Faker()
    async with async_session_factory() as session:
        existing = await session.scalar(select(func.count(User.id)))
        if existing:
            logger.info("Database already has %s users; skipping seed.", existing)
            return

        total_invoices = 0
        companies = [_build_company(fake) for _ in range(NUM_COMPANIES)]

        # The models declare no ORM relationships, so the unit of work cannot
        # infer that users must be inserted before their subscriptions and
        # invoices. Flush the parent rows first to satisfy the FKs.
        session.add_all([user for user, _, _ in companies])
        await session.flush()

        for _, subscription, invoices in companies:
            session.add(subscription)
            session.add_all(invoices)
            total_invoices += len(invoices)

        await session.commit()
        logger.info(
            "Seeded %s users, %s subscriptions, %s invoices.",
            NUM_COMPANIES,
            NUM_COMPANIES,
            total_invoices,
        )


async def main() -> None:
    """Entry point: seed and dispose the engine."""
    configure_logging()
    try:
        await seed()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
