"""Application configuration via pydantic-settings (env + .env file)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Reads configuration from environment variables and an optional .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    admin_username: str = "admin"
    admin_password: str = Field(default="", description="Initial password, read on first boot only.")
    data_dir: str = "./data"
    covers_dir: str = ""
    music_library_path: str = "./music"
    tz: str = "UTC"
    log_level: str = "INFO"
    dev_insecure_cookies: bool = False
    trusted_proxy_cidrs: str = "172.16.0.0/12,10.0.0.0/8"
    frontend_dist: str = "../frontend/dist"

    @field_validator("covers_dir", mode="before")
    @classmethod
    def default_covers_dir(cls, value: str, info) -> str:
        """Default COVERS_DIR to {DATA_DIR}/covers when not provided."""
        if value:
            return value
        return str(Path(info.data.get("data_dir", "./data")) / "covers")

    @field_validator("data_dir", "covers_dir")
    @classmethod
    def ensure_dirs(cls, value: str) -> str:
        """Create DATA_DIR and COVERS_DIR if they do not exist."""
        Path(value).mkdir(parents=True, exist_ok=True)
        return value

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "app.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()
