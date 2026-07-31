"""Postgres-backed LangGraph checkpointer (SRS §16.5, §16.9, §28).

Checkpoints are persistent workflow state, so they live in PostgreSQL - never in
Redis, which owns ephemeral runtime memory only (SRS §28 data ownership).

``AsyncPostgresSaver`` is built on psycopg (v3), not the app's asyncpg engine, so
the ``postgresql+asyncpg://`` SQLAlchemy URL has to be normalised to a plain
libpq DSN before it is handed over.

Usage - the saver owns a connection pool, so it must be used as a context
manager for the lifetime of the process that runs graphs::

    async with checkpointer_context() as checkpointer:
        graph = build_workflow_graph(checkpointer=checkpointer)
        ...
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

#: SQLAlchemy async driver prefixes that psycopg does not understand.
_DRIVER_PREFIXES = ("postgresql+asyncpg://", "postgresql+psycopg://")


def to_psycopg_dsn(database_url: str) -> str:
    """Convert a SQLAlchemy async URL into a libpq DSN psycopg accepts."""
    for prefix in _DRIVER_PREFIXES:
        if database_url.startswith(prefix):
            return "postgresql://" + database_url[len(prefix) :]
    return database_url


@asynccontextmanager
async def checkpointer_context() -> AsyncIterator[BaseCheckpointSaver]:
    """Yield a migrated ``AsyncPostgresSaver`` bound to the configured database.

    ``setup()`` creates the checkpoint tables if they do not exist and is
    idempotent, so every process that runs graphs may call it on boot.
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    dsn = to_psycopg_dsn(get_settings().database_url)
    async with AsyncPostgresSaver.from_conn_string(dsn) as checkpointer:
        await checkpointer.setup()
        logger.info("postgres checkpointer ready")
        yield checkpointer
