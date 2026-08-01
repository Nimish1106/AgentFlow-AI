"""Dispatcher process entrypoint: ``python -m app.dispatcher.main``.

Runs as its own Compose service so a long workflow never blocks an HTTP worker.
It owns the pieces the API deliberately does not: the compiled graph, the Groq
LLM, the MCP client, and the Postgres checkpointer.

Boot order matters. The checkpointer is entered *first* and kept open for the
process lifetime: ``AsyncPostgresSaver`` owns a connection pool, and a graph
compiled against a closed saver cannot resume an interrupted workflow.
"""

import asyncio
import contextlib
import logging
import signal

import redis.asyncio as redis

from app.config.settings import get_settings
from app.database.session import async_session_factory, engine
from app.dispatcher.consumer import WorkflowConsumer
from app.dispatcher.runner import WorkflowRunner
from app.graph.checkpointer import checkpointer_context
from app.graph.workflow import build_workflow_graph
from app.observability.logging import configure_logging
from app.observability.tracing import configure_tracing

logger = logging.getLogger(__name__)


#: Seconds of headroom between the blocking XREADGROUP window and the socket
#: read deadline. redis-py defaults socket_timeout to 5s, which is exactly the
#: default block window - the socket then times out every idle poll and the
#: consume loop logs a spurious error. The socket must outlive the block.
_SOCKET_TIMEOUT_HEADROOM_SECONDS = 5.0


def build_redis_client() -> redis.Redis:
    """Build a Redis client whose read deadline outlives a blocking stream read."""
    settings = get_settings()
    return redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_timeout=(
            settings.dispatcher_block_ms / 1000 + _SOCKET_TIMEOUT_HEADROOM_SECONDS
        ),
    )


async def run_dispatcher() -> None:
    """Wire the graph, checkpointer, queue and runner, then consume forever."""
    configure_logging()
    # Node and MCP-tool spans (SRS §42). A no-op unless OTEL_ENABLED is set,
    # so the dispatcher runs identically with no collector present.
    configure_tracing()
    logger.info("workflow dispatcher starting")

    client = build_redis_client()
    try:
        async with checkpointer_context() as checkpointer:
            graph = build_workflow_graph(checkpointer=checkpointer)
            runner = WorkflowRunner(graph, async_session_factory)
            consumer = WorkflowConsumer(client, runner)

            _install_signal_handlers(consumer)
            await consumer.run_forever()
    finally:
        await client.aclose()
        await engine.dispose()
        logger.info("workflow dispatcher stopped")


def _install_signal_handlers(consumer: WorkflowConsumer) -> None:
    """Stop the consume loop cleanly on SIGTERM/SIGINT.

    Compose sends SIGTERM on ``docker compose down``; draining the current batch
    beats being killed mid-workflow. Not every platform supports every signal,
    so failures here are non-fatal.
    """
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError, AttributeError, ValueError):
            loop.add_signal_handler(sig, consumer.stop)


def main() -> None:
    """Console entrypoint."""
    asyncio.run(run_dispatcher())


if __name__ == "__main__":
    main()
