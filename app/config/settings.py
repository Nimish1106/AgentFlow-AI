"""Application configuration loaded from environment variables / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings (SRS §43: secrets come from .env)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "AgentFlow AI"
    app_version: str = "1.0.0"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://agentflow:agentflow@localhost:5432/agentflow"
    redis_url: str = "redis://localhost:6379/0"
    workflow_stream: str = "agentflow:workflow_queue"

    estimated_wait_time_seconds: int = 30

    # Enterprise MCP Server (SRS §31, §44)
    mcp_server_url: str = "http://enterprise-mcp:8000"
    mcp_tool_timeout_seconds: float = 10.0

    # Agent tool loop + retry policy (SRS §30, §41)
    agent_max_tool_rounds: int = 8
    mcp_retry_max_attempts: int = 3
    mcp_retry_backoff_seconds: float = 0.5

    # RAG / Qdrant (SRS §8, §20, §32, §33). The embedding model is configurable
    # per SRS §46; both sides of the pipeline (ingestion + retrieval) read it
    # from here so indexed vectors and query vectors always match.
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "knowledge"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: int = 384
    rag_top_k: int = 5
    # bge cosine scores have a high floor (~0.5 even for unrelated text);
    # measured on the seed corpus: relevant hits score >=0.7, nonsense <=0.52.
    rag_score_threshold: float = 0.6
    knowledge_docs_dir: str = "docs/knowledge"
    chunk_size: int = 1200
    chunk_overlap: int = 200

    # Risk Engine + HITL governance (SRS §38, §39)
    hitl_refund_threshold: float = 1000.0
    hitl_confidence_threshold: float = 0.6

    # Queue dispatcher (SRS §14: FastAPI queues jobs; the dispatcher runs them)
    dispatcher_consumer_group: str = "agentflow-dispatcher"
    dispatcher_consumer_name: str = "dispatcher-1"
    dispatcher_block_ms: int = 5000
    # Optional webhook the graph Dispatcher node POSTs the final response to.
    # Empty = webhook delivery disabled (SRS §13 step 14: a failed webhook
    # logs and continues - it never crashes the workflow).
    dispatch_webhook_url: str = ""
    dispatch_webhook_timeout_seconds: float = 5.0

    # Operations dashboard (Phase 7). The React app is served from its own
    # origin, so the API must allow it explicitly - never a wildcard (SRS §43).
    # Comma-separated so it can be overridden by one env var.
    cors_allow_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )

    # Observability (SRS §42). Off by default: enabling it must be a deliberate
    # act, and the unit suite / offline runs need no collector listening.
    # With tracing on and no endpoint set, spans go to the console exporter.
    otel_enabled: bool = False
    otel_service_name: str = "agentflow"
    otel_exporter_otlp_endpoint: str = ""

    # LangSmith Observability
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "agentflow"
    langsmith_endpoint: str = "https://api.smith.langchain.com"

    # LLM (SRS §8: Groq). Agents never read env vars directly (SRS §46) - they
    # receive an LLM built from these settings.
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.0
    llm_max_retries: int = 3

    @property
    def cors_allow_origins_list(self) -> list[str]:
        """Parse ``cors_allow_origins`` into a list, dropping blanks."""
        return [
            origin.strip()
            for origin in self.cors_allow_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
