"""Unit tests for AccountService (unlock transitions, feature flags)."""

import uuid

import pytest

from app.models import User
from app.models.enums import AccountStatus
from app.services.account_service import AccountService
from app.services.exceptions import CustomerNotFoundError


async def _make_user(session, status: AccountStatus = AccountStatus.ACTIVE) -> User:
    user = User(
        company_name="Acme Corp",
        full_name="Alice Admin",
        email=f"{uuid.uuid4()}@acme.test",
        account_status=status,
    )
    session.add(user)
    await session.commit()
    return user


async def test_get_customer(session_factory):
    async with session_factory() as session:
        user = await _make_user(session)
        found = await AccountService(session).get_customer(user.id)
        assert found.email == user.email


async def test_get_customer_missing(session_factory):
    async with session_factory() as session:
        with pytest.raises(CustomerNotFoundError):
            await AccountService(session).get_customer(uuid.uuid4())


async def test_unlock_dashboard_from_locked(session_factory):
    async with session_factory() as session:
        user = await _make_user(session, AccountStatus.LOCKED)

        result = await AccountService(session).unlock_dashboard(user.id)
        assert result["unlocked"] is True
        assert result["previous_status"] == "locked"
        assert result["new_status"] == "active"

        await session.refresh(user)
        assert user.account_status is AccountStatus.ACTIVE


@pytest.mark.parametrize(
    "status", [AccountStatus.ACTIVE, AccountStatus.SUSPENDED]
)
async def test_unlock_dashboard_rejected_when_not_locked(session_factory, status):
    async with session_factory() as session:
        user = await _make_user(session, status)

        result = await AccountService(session).unlock_dashboard(user.id)
        assert result["unlocked"] is False
        assert result["new_status"] == status.value

        await session.refresh(user)
        assert user.account_status is status


async def test_update_feature_flag_set_and_overwrite(session_factory):
    async with session_factory() as session:
        user = await _make_user(session)
        service = AccountService(session)

        result = await service.update_feature_flag(user.id, "beta_dashboard", True)
        assert result["feature_flags"] == {"beta_dashboard": True}

        result = await service.update_feature_flag(user.id, "beta_dashboard", False)
        assert result["feature_flags"] == {"beta_dashboard": False}

        result = await service.update_feature_flag(user.id, "sso", True)
        assert result["feature_flags"] == {"beta_dashboard": False, "sso": True}

        await session.refresh(user)
        assert user.feature_flags == {"beta_dashboard": False, "sso": True}
