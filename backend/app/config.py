"""Runtime configuration, read from the environment with sane defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class Settings:
    app_name: str = "ReadIt"
    secret_key: str = field(
        default_factory=lambda: os.getenv("READIT_SECRET_KEY", "readit-dev-secret-change-me")
    )
    token_ttl_seconds: int = field(default_factory=lambda: _env_int("READIT_TOKEN_TTL", 60 * 60 * 24 * 30))

    # Bootstrap admin account. The first user matching this email is an admin.
    admin_email: str = field(default_factory=lambda: os.getenv("READIT_ADMIN_EMAIL", "admin@readit.local"))
    admin_password: str = field(default_factory=lambda: os.getenv("READIT_ADMIN_PASSWORD", "readit-admin"))

    # Persistence is a convenience layer on top of the in-memory store.
    persist: bool = field(default_factory=lambda: _env_bool("READIT_PERSIST", True))
    snapshot_path: str = field(
        default_factory=lambda: os.getenv("READIT_SNAPSHOT", "data/readit_snapshot.json")
    )
    snapshot_interval_seconds: int = field(default_factory=lambda: _env_int("READIT_SNAPSHOT_INTERVAL", 60))

    # Media library. Binaries live on disk; only metadata goes in the snapshot,
    # so a few hundred images never bloat the JSON.
    media_dir: str = field(default_factory=lambda: os.getenv("READIT_MEDIA_DIR", "data/media"))
    media_max_bytes: int = field(default_factory=lambda: _env_int("READIT_MEDIA_MAX_BYTES", 25 * 1024 * 1024))
    media_max_edge: int = field(default_factory=lambda: _env_int("READIT_MEDIA_MAX_EDGE", 2048))
    media_thumb_edge: int = field(default_factory=lambda: _env_int("READIT_MEDIA_THUMB_EDGE", 512))
    # Vision models gain little from full resolution and cost a lot for it.
    media_vision_edge: int = field(default_factory=lambda: _env_int("READIT_MEDIA_VISION_EDGE", 1024))
    media_fetch_timeout: float = field(default_factory=lambda: _env_float("READIT_MEDIA_FETCH_TIMEOUT", 20.0))

    # Simulation engine.
    simulation_enabled: bool = field(default_factory=lambda: _env_bool("READIT_SIMULATION", True))
    tick_seconds: float = field(default_factory=lambda: _env_float("READIT_TICK_SECONDS", 12.0))
    max_concurrent_generations: int = field(default_factory=lambda: _env_int("READIT_MAX_CONCURRENCY", 4))

    # LLM defaults. Keys entered through the admin UI take precedence over these.
    openrouter_api_key: str = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY", ""))
    openai_api_key: str = field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    google_api_key: str = field(default_factory=lambda: os.getenv("GOOGLE_API_KEY", ""))

    request_timeout_seconds: float = field(default_factory=lambda: _env_float("READIT_LLM_TIMEOUT", 90.0))

    cors_origins: list[str] = field(
        default_factory=lambda: os.getenv(
            "READIT_CORS",
            "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173",
        ).split(",")
    )

    @property
    def effective_snapshot_path(self) -> str | None:
        return self.snapshot_path if self.persist else None


settings = Settings()
