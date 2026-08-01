"""Dispatcher node (SRS §14, §13 step 14): deliver the final response.

No reasoning, no LLM - routing only. The node records the delivery channels the
response went out on and, when a webhook is configured, POSTs the response to
it with ``httpx``.

SRS §13 step 14 is explicit: a failed webhook logs the failure but must NOT
crash the workflow. The ticket resolution is already complete by the time this
node runs, so delivery failure is recorded in ``errors`` and the workflow still
finishes ``completed``.

This node owns the terminal ``workflow_status="completed"`` transition (SRS §37:
Dispatcher is the last node before END).

The customer-portal channel is always "delivered": the response is persisted in
GraphState and read back through ``GET /tickets/{id}``, so no outbound call is
needed for it.
"""

import logging
import time
from typing import Dict, List

from app.config.settings import get_settings
from app.graph.state import GraphState, build_node_execution

logger = logging.getLogger(__name__)

NODE_NAME = "dispatcher"

#: shared_context key holding the delivery record.
CONTEXT_KEY = "dispatch"

CHANNEL_PORTAL = "customer_portal"
CHANNEL_WEBHOOK = "webhook"


async def _post_webhook(url: str, payload: Dict, timeout: float) -> None:
    """POST the response to the configured webhook (SRS §16.11: httpx, async)."""
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()


async def dispatcher_node(state: GraphState) -> Dict:
    """Route the final response to its delivery channels (SRS §14)."""
    started = time.perf_counter()
    settings = get_settings()
    workflow_id = state.get("workflow_id", "")
    final_response = state.get("final_response")

    delivered: List[str] = []
    failed: List[str] = []
    errors: List[str] = []

    if not final_response:
        # Nothing to deliver: a rejected or failed workflow reaches END without
        # a customer-facing response. Record it rather than inventing one.
        logger.warning(
            "workflow_id=%s node=%s no final_response to deliver",
            workflow_id,
            NODE_NAME,
        )
    else:
        delivered.append(CHANNEL_PORTAL)

        if settings.dispatch_webhook_url:
            payload = {
                "workflow_id": workflow_id,
                "ticket_id": state.get("ticket_id", ""),
                "customer_id": state.get("customer_id", ""),
                "response": final_response,
                "approval_status": state.get("approval_status"),
                "risk_score": state.get("risk_score", 0.0),
            }
            try:
                await _post_webhook(
                    settings.dispatch_webhook_url,
                    payload,
                    settings.dispatch_webhook_timeout_seconds,
                )
                delivered.append(CHANNEL_WEBHOOK)
            except Exception as exc:  # noqa: BLE001 - delivery must not crash
                # SRS §13 step 14: log and continue; resolution is already done.
                logger.warning(
                    "workflow_id=%s node=%s webhook delivery failed: %s",
                    workflow_id,
                    NODE_NAME,
                    exc,
                )
                failed.append(CHANNEL_WEBHOOK)
                errors.append(f"{NODE_NAME}: webhook delivery failed: {exc}")

    dispatch = {
        "delivered": delivered,
        "failed": failed,
        "response_delivered": bool(delivered),
    }

    elapsed_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "workflow_id=%s node=%s delivered=%s failed=%s execution_time_ms=%.1f "
        "retry_count=%s",
        workflow_id,
        NODE_NAME,
        delivered,
        failed,
        elapsed_ms,
        state.get("retry_count", 0),
    )

    update: Dict = {
        "current_node": NODE_NAME,
        "workflow_status": "completed",
        "shared_context": {CONTEXT_KEY: dispatch},
        "node_executions": [
            build_node_execution(
                node=NODE_NAME,
                status="success",
                execution_time_ms=elapsed_ms,
                summary=(
                    f"delivered={delivered or ['nothing']}"
                    + (f" failed={failed}" if failed else "")
                ),
            )
        ],
    }
    if errors:
        update["errors"] = errors
    return update
