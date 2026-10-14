from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str | None = None
    openai_model: str = "gpt-5"
    openai_embedding_model: str = "text-embedding-3-small"

    tavily_api_key: str | None = None

    app_env: str = "development"
    log_level: str = "INFO"
    port: int = 8080

    api_max_request_body_bytes: int = Field(default=65_536, ge=1024, le=1_048_576)
    api_max_active_requests: int = Field(default=1, ge=1, le=64)
    api_max_waiting_requests: int = Field(default=0, ge=0, le=128)
    api_request_timeout_seconds: float = Field(default=180, gt=0, le=300, allow_inf_nan=False)
    api_queue_timeout_seconds: float = Field(default=30, gt=0, le=300, allow_inf_nan=False)

    agent_max_tool_calls: int = Field(default=8, ge=1, le=32)
    agent_max_model_calls: int = Field(default=6, ge=1, le=12)
    agent_max_context_characters: int = Field(default=64_000, ge=20_000, le=256_000)
    agent_max_completion_tokens: int = Field(default=4096, ge=1024, le=8192)
    agent_max_sessions: int = Field(default=128, ge=1, le=1024)
    agent_session_ttl_seconds: float = Field(default=1800, ge=60, le=86400, allow_inf_nan=False)
    agent_history_turns: int = Field(default=6, ge=2, le=20)
    provider_timeout_seconds: float = Field(default=30, gt=0, le=45, allow_inf_nan=False)
    provider_max_retries: int = Field(default=0, ge=0, le=1)

    corpus_attribution_path: Path | None = None

    documents_dir: Path = Path("./data/papers")
    workspace_manifest_path: Path = Path("./data/samples/manifest.json")
    chroma_persist_dir: Path = Path("./data/index")
    chroma_collection: str = "veridex_documents"

    mcp_servers_config: Path = Path("./mcp_config.json")


settings = Settings()
