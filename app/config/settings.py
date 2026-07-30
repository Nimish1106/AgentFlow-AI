"""Application configuration loaded from environment variables / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings (SRS §43: secrets come from .env)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "AgentFlow AI"
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

    # LLM (SRS §8: Groq). Agents never read env vars directly (SRS §46) - they
    # receive an LLM built from these settings.
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.0
    llm_max_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
