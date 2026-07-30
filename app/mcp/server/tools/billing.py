"""Billing tool namespace for the Enterprise MCP Server (SRS §31)."""

from typing import Optional

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession

from app.mcp.schemas import InvoiceResult, RefundCalculation, SubscriptionResult
from app.mcp.server.runtime import parse_uuid, run_tool
from app.services.billing_service import BillingService


def register(mcp: FastMCP) -> None:
    """Register billing tools on the server."""

    @mcp.tool(name="billing_get_invoice")
    async def billing_get_invoice(
        invoice_id: str, workflow_id: Optional[str] = None
    ) -> dict:
        """Fetch an invoice by id, including amount and payment status."""

        async def handler(session: AsyncSession) -> dict:
            invoice = await BillingService(session).get_invoice(
                parse_uuid(invoice_id, "invoice_id")
            )
            return InvoiceResult(
                id=str(invoice.id),
                user_id=str(invoice.user_id),
                amount=invoice.amount,
                currency=invoice.currency,
                payment_status=invoice.payment_status.value,
            ).model_dump(mode="json")

        return await run_tool(
            "billing_get_invoice",
            handler,
            arguments={"invoice_id": invoice_id},
            workflow_id=workflow_id,
        )

    @mcp.tool(name="billing_get_subscription")
    async def billing_get_subscription(
        customer_id: str, workflow_id: Optional[str] = None
    ) -> dict:
        """Fetch the customer's most recent subscription."""

        async def handler(session: AsyncSession) -> dict:
            subscription = await BillingService(session).get_subscription(
                parse_uuid(customer_id, "customer_id")
            )
            return SubscriptionResult(
                id=str(subscription.id),
                user_id=str(subscription.user_id),
                plan=subscription.plan.value,
                monthly_price=subscription.monthly_price,
                renewal_date=subscription.renewal_date.isoformat(),
                subscription_status=subscription.subscription_status.value,
            ).model_dump(mode="json")

        return await run_tool(
            "billing_get_subscription",
            handler,
            arguments={"customer_id": customer_id},
            workflow_id=workflow_id,
        )

    @mcp.tool(name="billing_calculate_refund")
    async def billing_calculate_refund(
        invoice_id: str, workflow_id: Optional[str] = None
    ) -> dict:
        """Deterministically evaluate refund eligibility for an invoice."""

        async def handler(session: AsyncSession) -> dict:
            decision = await BillingService(session).calculate_refund(
                parse_uuid(invoice_id, "invoice_id")
            )
            return RefundCalculation(**decision).model_dump(mode="json")

        return await run_tool(
            "billing_calculate_refund",
            handler,
            arguments={"invoice_id": invoice_id},
            workflow_id=workflow_id,
        )
