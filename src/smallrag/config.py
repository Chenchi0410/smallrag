from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables or a local .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    confluence_kb_url: str = "https://knowledge-base.example"
    confluence_kb_api_key: SecretStr | None = None
    confluence_kb_verify_ssl: bool = False

    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str = "qwen3-8b"
    llm_verify_ssl: bool = True
    llm_enable_thinking: bool = False

    rag_default_top_k: int = Field(default=5, ge=1, le=20)
    rag_default_alpha: float = Field(default=0.5, ge=0, le=1)
    rag_default_max_context_chars: int = Field(default=20_000, ge=1_000, le=200_000)
    rag_request_timeout_seconds: float = Field(default=60, gt=0, le=300)

    server_host: str = "0.0.0.0"
    server_port: int = Field(default=18_082, ge=1, le=65_535)
    https_certfile: str | None = None
    https_keyfile: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
