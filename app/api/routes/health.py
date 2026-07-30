"""Health endpoint: verifies PostgreSQL and Redis connectivity."""

import logging

import redis.asyncio as redis
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import HealthResponse
from app.database.redis import get_redis
from app.database.session import get_db

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    session: AsyncSession = Depends(get_db),
    redis_client: redis.Redis = Depends(get_redis),
) -> JSONResponse:
    """Return component health; 503 when any dependency is unreachable."""
    database = "ok"
    redis_status = "ok"

    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database health check failed")
        database = "unavailable"

    try:
        await redis_client.ping()
    except Exception:
        logger.exception("Redis health check failed")
        redis_status = "unavailable"

    healthy = database == "ok" and redis_status == "ok"
    payload = HealthResponse(
        status="ok" if healthy else "degraded",
        database=database,
        redis=redis_status,
    )
    return JSONResponse(
        status_code=200 if healthy else 503, content=payload.model_dump()
    )
