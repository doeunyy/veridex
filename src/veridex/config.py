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
    api_max_active_requests: int = Field(default=4, ge=1, le=64)
    api_max_waiting_requests: int = Field(default=8, ge=0, le=128)
    api_request_timeout_seconds: float = Field(default=180, gt=0, le=300, allow_inf_nan=False)
    api_queue_timeout_seconds: float = Field(default=30, gt=0, le=300, allow_inf_nan=False)

    documents_dir: Path = Path("./data/papers")
    workspace_manifest_path: Path = Path("./data/samples/manifest.json")
    chroma_persist_dir: Path = Path("./data/index")
    chroma_collection: str = "veridex_documents"

    mcp_servers_config: Path = Path("./mcp_config.json")


settings = Settings()
