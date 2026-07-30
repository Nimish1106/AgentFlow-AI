"""LLM construction for reasoning nodes (SRS §8: Groq).

Agents and nodes never read environment variables directly (SRS §46); they are
handed a chat model built here from validated settings.
"""

from functools import lru_cache

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_groq import ChatGroq

from app.config.settings import get_settings


class LLMNotConfiguredError(RuntimeError):
    """Raised when an LLM is requested but no Groq API key is configured."""


@lru_cache
def get_llm() -> BaseChatModel:
    """Return a cached Groq chat model built from application settings.

    Raises:
        LLMNotConfiguredError: if ``GROQ_API_KEY`` is unset. Failing here keeps
            the misconfiguration at startup rather than surfacing it as an opaque
            auth error midway through a workflow.
    """
    settings = get_settings()
    if not settings.groq_api_key:
        raise LLMNotConfiguredError(
            "GROQ_API_KEY is not set; the Supervisor cannot perform reasoning."
        )

    return ChatGroq(
        model_name=settings.groq_model,
        temperature=settings.llm_temperature,
        groq_api_key=settings.groq_api_key,
        max_retries=settings.llm_max_retries,
    )
