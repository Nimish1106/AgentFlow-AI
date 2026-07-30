"""Account business logic backing the Enterprise MCP account tools (SRS §31)."""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.models.enums import AccountStatus
from app.services.exceptions import CustomerNotFoundError

logger = logging.getLogger(__name__)


class AccountService:
    """Reads and updates enterprise customer accounts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_customer(self, customer_id: uuid.UUID) -> User:
        """Return a customer by id."""
        customer = await self._session.get(User, customer_id)
        if customer is None:
            raise CustomerNotFoundError(str(customer_id))
        return customer

    async def unlock_dashboard(self, customer_id: uuid.UUID) -> dict:
        """Unlock a locked customer dashboard.

        Only the LOCKED -> ACTIVE transition is allowed; active or suspended
        accounts are left untouched and the refusal is reported to the caller.
        """
        customer = await self.get_customer(customer_id)
        previous_status = customer.account_status

        if previous_status is not AccountStatus.LOCKED:
            return {
                "customer_id": str(customer.id),
                "unlocked": False,
                "previous_status": previous_status.value,
                "new_status": previous_status.value,
                "reason": f"Account is {previous_status.value}, not locked.",
            }

        customer.account_status = AccountStatus.ACTIVE
        await self._session.commit()
        logger.info("customer_id=%s dashboard unlocked", customer.id)
        return {
            "customer_id": str(customer.id),
            "unlocked": True,
            "previous_status": previous_status.value,
            "new_status": AccountStatus.ACTIVE.value,
            "reason": "Dashboard unlocked.",
        }

    async def update_feature_flag(
        self, customer_id: uuid.UUID, flag_name: str, enabled: bool
    ) -> dict:
        """Set a feature flag for a customer."""
        customer = await self.get_customer(customer_id)

        # Reassign a copy so SQLAlchemy change-tracking sees the JSON update.
        flags = dict(customer.feature_flags or {})
        flags[flag_name] = enabled
        customer.feature_flags = flags
        await self._session.commit()

        logger.info(
            "customer_id=%s feature_flag=%s enabled=%s", customer.id, flag_name, enabled
        )
        return {
            "customer_id": str(customer.id),
            "flag_name": flag_name,
            "enabled": enabled,
            "feature_flags": flags,
        }
