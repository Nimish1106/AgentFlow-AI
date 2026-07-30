"""Async Redis client management (queue + ephemeral memory only, SRS §19)."""

from collections.abc import AsyncGenerator

import redis.asyncio as redis

from app.config.settings import get_settings

_pool: redis.ConnectionPool | None = None


def _get_pool() -> redis.ConnectionPool:
    """Lazily create the shared connection pool."""
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(
            get_settings().redis_url, decode_responses=True
        )
    return _pool


async def get_redis() -> AsyncGenerator[redis.Redis, None]:
    """FastAPI dependency yielding a Redis client backed by the shared pool."""
    client = redis.Redis(connection_pool=_get_pool())
    try:
        yield client
    finally:
        await client.aclose()


async def close_redis_pool() -> None:
    """Dispose the shared pool at application shutdown."""
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None
