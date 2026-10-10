from pathlib import Path

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

    documents_dir: Path = Path("./data/papers")
    workspace_manifest_path: Path = Path("./data/samples/manifest.json")
    chroma_persist_dir: Path = Path("./data/index")
    chroma_collection: str = "veridex_documents"

    mcp_servers_config: Path = Path("./mcp_config.json")


settings = Settings()
