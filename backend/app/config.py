"""Application settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Load OPENAI_API_KEY / ANTHROPIC_API_KEY into os.environ so the SDKs see them.
# pydantic-settings only maps CREWOPS_* fields and would otherwise ignore these.
load_dotenv(BACKEND_ROOT / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CREWOPS_",
        env_file=str(BACKEND_ROOT / ".env"),
        extra="ignore",
    )

    app_name: str = "Crew Ops Advisor"
    version: str = "1.0.0"

    #: Where the shipped dataset lives. Empty means ``data/data-seed-{data_seed}/``,
    #: which is generated on startup if the folder is missing or incomplete.
    data_dir: str = ""
    #: RNG seed for the synthetic world. Engineered ids (C-1042, P-2291, …)
    #: stay fixed; names, spare crew, history and answer keys vary with seed.
    data_seed: int = 42

    #: PostgreSQL in docker-compose; SQLite locally so the API runs with no
    #: infrastructure at all. The world snapshot is read from JSON either way --
    #: the database holds traces, decisions, alerts and eval history.
    database_url: str = f"sqlite:///{BACKEND_ROOT / 'crewops.db'}"
    db_echo: bool = False
    persist_traces: bool = True

    #: The dataset is frozen at this instant; the virtual clock starts here.
    snapshot_utc: str = "2026-09-14T18:00:00Z"

    #: openai | anthropic | auto. auto uses the first available key
    #: (Anthropic if both are set).
    llm_provider: str = "auto"
    #: Empty means the provider default (claude-opus-5 or gpt-4.1).
    model: str = ""

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    scheduler_enabled: bool = True
    #: Seconds of wall-clock between watcher passes (demo cadence, not ops).
    watcher_interval_seconds: int = 300

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith(("postgresql", "postgres"))

    @model_validator(mode="after")
    def _default_data_dir(self) -> Settings:
        if not (self.data_dir or "").strip():
            object.__setattr__(
                self,
                "data_dir",
                str(BACKEND_ROOT / "data" / f"data-seed-{int(self.data_seed)}"),
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def data_dir() -> str:
    return get_settings().data_dir


os.environ.setdefault("CREWOPS_LLM_PROVIDER", get_settings().llm_provider)
if get_settings().model:
    os.environ.setdefault("CREWOPS_MODEL", get_settings().model)
