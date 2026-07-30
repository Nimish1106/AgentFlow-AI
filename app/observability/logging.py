"""Logging configuration for all application components."""

import logging

from app.config.settings import get_settings

LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"


def configure_logging() -> None:
    """Configure the root logger once at application startup."""
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format=LOG_FORMAT,
        force=True,
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
