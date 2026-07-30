"""Account tool namespace for the Enterprise MCP Server (SRS §31)."""

from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.schemas import CustomerResult
from app.mcp.server.runtime import parse_uuid, run_tool
from app.services.account_service import AccountService


def register(mcp: FastMCP) -> None:
    """Register account tools on the server."""

    @mcp.tool(name="account_get_customer")
    async def account_get_customer(
        customer_id: str, workflow_id: Optional[str] = None
    ) -> dict:
        """Fetch a customer account, including status and feature flags."""

        async def handler(session: AsyncSession) -> dict:
            customer = await AccountService(session).get_customer(
                parse_uuid(customer_id, "customer_id")
            )
            return CustomerResult(
                id=str(customer.id),
                company_name=customer.company_name,
                full_name=customer.full_name,
                email=customer.email,
                account_status=customer.account_status.value,
                role=customer.role.value,
                feature_flags=customer.feature_flags or {},
            ).model_dump(mode="json")

        return await run_tool(
            "account_get_customer",
            handler,
            arguments={"customer_id": customer_id},
            workflow_id=workflow_id,
        )

    @mcp.tool(name="account_unlock_dashboard")
    async def account_unlock_dashboard(
        customer_id: str, workflow_id: Optional[str] = None
    ) -> dict:
        """Unlock a locked customer dashboard (locked -> active only)."""

        async def handler(session: AsyncSession) -> dict:
            return await AccountService(session).unlock_dashboard(
                parse_uuid(customer_id, "customer_id")
            )

        return await run_tool(
            "account_unlock_dashboard",
            handler,
            arguments={"customer_id": customer_id},
            workflow_id=workflow_id,
        )

    @mcp.tool(name="account_update_feature_flag")
    async def account_update_feature_flag(
        customer_id: str,
        flag_name: str,
        enabled: bool,
        workflow_id: Optional[str] = None,
    ) -> dict:
        """Enable or disable a feature flag for a customer."""

        async def handler(session: AsyncSession) -> dict:
            return await AccountService(session).update_feature_flag(
                parse_uuid(customer_id, "customer_id"), flag_name, enabled
            )

        return await run_tool(
            "account_update_feature_flag",
            handler,
            arguments={
                "customer_id": customer_id,
                "flag_name": flag_name,
                "enabled": enabled,
            },
            workflow_id=workflow_id,
        )
