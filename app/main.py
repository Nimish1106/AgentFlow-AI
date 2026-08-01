"""FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import approvals, dashboard, health, tickets, workflows
from app.config.settings import get_settings
from app.database.redis import close_redis_pool
from app.database.session import engine
from app.observability.logging import configure_logging
from app.observability.tracing import configure_tracing

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Configure logging and tracing on startup; release connections on shutdown."""
    configure_logging()
    # Instruments this app's request handling (SRS §42). A no-op unless
    # OTEL_ENABLED is set, so no collector is required to run the API.
    configure_tracing(app)
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

# The dashboard is served from a different origin in development (Vite on
# :5173) and through its own container in Compose, so the browser needs CORS.
# Origins come from settings, never a wildcard (SRS §43).
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_allow_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(health.router)
# Registered before the parameterised ticket/workflow routers: FastAPI matches
# in registration order, and `/workflows/{workflow_id}` would otherwise swallow
# the literal `/workflows` list path's siblings.
app.include_router(dashboard.router)
app.include_router(tickets.router)
app.include_router(workflows.router)
app.include_router(approvals.router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never expose internal exceptions to clients (SRS §46 API rules)."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})
