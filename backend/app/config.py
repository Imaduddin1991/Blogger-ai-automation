"""Application settings loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_here = Path(__file__).resolve().parent
_DEFAULT_DATA_DIR = str(_here.parent / "data")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_here.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "blogger-ai-automation"
    host: str = "127.0.0.1"
    port: int = 8000

    data_dir: str = _DEFAULT_DATA_DIR
    database_url: str = f"sqlite:///{_DEFAULT_DATA_DIR}/blogger_ai.db"

    # Ollama provider endpoint. Accepts OLLAMA_BASE_URL or OLLAMA_URL from the
    # environment so the same build works against a local or remote (e.g.
    # Windows-hosted) Ollama without code changes. Default is localhost.
    ollama_url: str = Field(
        default="http://127.0.0.1:11434",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "OLLAMA_URL", "ollama_url"),
    )
    ollama_default_model: str = "qwen2.5:1.5b"

    local_auth_token: str = ""
    encryption_key: str = ""

    # Blogger OAuth 2.0 (Phase 5)
    blogger_client_id: str = ""
    blogger_client_secret: str = ""
    blogger_redirect_uri: str = "http://127.0.0.1:8000/api/blogger/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()
