"""Application settings loaded from environment / .env."""

from functools import lru_cache
from pathlib import Path

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

    ollama_url: str = "http://127.0.0.1:11434"
    ollama_default_model: str = "qwen2.5:1.5b"

    local_auth_token: str = ""
    encryption_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
