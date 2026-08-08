"""LangSmith observability configuration module.

Configures standard environment variables required by LangChain / LangGraph
and LangSmith to trace workflow execution, graph nodes, LLM calls, and tools.

Tracing is optional and off by default: enabling it requires setting
LANGSMITH_TRACING=true (or LANGCHAIN_TRACING_V2=true) and providing a valid
API key via LANGSMITH_API_KEY or LANGCHAIN_API_KEY.
"""

import logging
import os
from typing import Optional

from app.config.settings import get_settings

logger = logging.getLogger(__name__)

_configured = False
_enabled = False


def configure_langsmith() -> bool:
    """Initialize LangSmith configuration if enabled via environment or settings.

    Safe to call multiple times (idempotent). Does not raise exceptions if setup
    fails or credentials are missing.

    Returns:
        True if LangSmith tracing is active, False otherwise.
    """
    global _configured, _enabled
    if _configured:
        return _enabled

    _configured = True
    settings = get_settings()

    tracing_requested = (
        os.getenv("LANGSMITH_TRACING", "").lower() in ("true", "1")
        or os.getenv("LANGCHAIN_TRACING_V2", "").lower() in ("true", "1")
        or settings.langsmith_tracing
    )

    api_key = (
        os.getenv("LANGSMITH_API_KEY")
        or os.getenv("LANGCHAIN_API_KEY")
        or settings.langsmith_api_key
        or ""
    ).strip()

    project = (
        os.getenv("LANGSMITH_PROJECT")
        or os.getenv("LANGCHAIN_PROJECT")
        or settings.langsmith_project
        or "agentflow"
    ).strip()

    endpoint = (
        os.getenv("LANGSMITH_ENDPOINT")
        or os.getenv("LANGCHAIN_ENDPOINT")
        or settings.langsmith_endpoint
        or "https://api.smith.langchain.com"
    ).strip()

    if tracing_requested and api_key:
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGSMITH_API_KEY"] = api_key
        os.environ["LANGCHAIN_API_KEY"] = api_key
        os.environ["LANGSMITH_PROJECT"] = project
        os.environ["LANGCHAIN_PROJECT"] = project
        os.environ["LANGSMITH_ENDPOINT"] = endpoint
        os.environ["LANGCHAIN_ENDPOINT"] = endpoint
        _enabled = True
        logger.info("LangSmith tracing enabled (project: %s)", project)
    elif tracing_requested and not api_key:
        logger.warning(
            "LangSmith tracing enabled (LANGSMITH_TRACING=true) but no API key "
            "provided in LANGSMITH_API_KEY or LANGCHAIN_API_KEY; continuing untraced"
        )
        _enabled = False
    else:
        logger.debug("LangSmith tracing disabled")
        _enabled = False

    return _enabled


def is_langsmith_enabled() -> bool:
    """Return True if LangSmith tracing is currently active."""
    return _enabled


def reset_for_testing() -> None:
    """Reset module configuration state (for unit testing)."""
    global _configured, _enabled
    _configured = False
    _enabled = False
