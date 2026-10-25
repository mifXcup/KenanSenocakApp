from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def default_data_dir() -> Path:
    explicit = os.getenv("KS_DATA_DIR")
    if explicit:
        return Path(explicit)
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "Kenan Senocak Yonetim"
    return Path.home() / ".ks-yonetim"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KS_", extra="ignore")

    data_dir: Path = default_data_dir()
    database_url: str | None = None
    sidecar_token: str | None = None
    environment: str = "local"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'kenan-senocak.db').as_posix()}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
