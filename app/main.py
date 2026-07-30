"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.routes import health, tickets, workflows
from app.config.settings import get_settings
from app.database.redis import close_redis_pool
from app.database.session import engine
from app.observability.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure logging on startup; release connections on shutdown."""
    configure_logging()
    logger.info("%s starting", get_settings().app_name)
    yield
    await close_redis_pool()
    await engine.dispose()
    logger.info("%s stopped", get_settings().app_name)


app = FastAPI(
    title=get_settings().app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(tickets.router)
app.include_router(workflows.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never expose internal exceptions to clients (SRS §46 API rules)."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
