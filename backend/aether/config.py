"""Runtime configuration.

The single most important setting here is :attr:`Settings.mode`. ``replay`` serves
extraction from cached fixtures with no network access at all, and is the demo path.
``live`` calls the model. The demo must never depend on ``live`` working.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["Mode", "Settings", "get_settings", "install_tls_trust"]

REPO_ROOT = Path(__file__).resolve().parents[2]


class Mode(StrEnum):
    REPLAY = "replay"
    LIVE = "live"


class Settings(BaseSettings):
    """Environment-driven settings. Secrets are read from the environment only."""

    model_config = SettingsConfigDict(
        env_prefix="AETHER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: Mode = Mode.REPLAY
    model_id: str = "claude-opus-5"
    engine_version: str = "0.1.0"

    #: This machine's outbound TLS is intercepted by antivirus software. Python's
    #: default context and certifi both reject the injected CA; the Windows trust
    #: store accepts it. See scripts/verify_env.py.
    use_truststore: bool = True

    db_url: str = "sqlite:///./aether.db"
    # Both spellings of loopback: a browser treats localhost and 127.0.0.1 as
    # different origins, and the dev server is reachable on either.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @property
    def api_key(self) -> str:
        """Read lazily and never stored on the model, so it cannot be serialised."""
        import os

        return os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def live_available(self) -> bool:
        return self.mode is Mode.LIVE and bool(self.api_key)

    @property
    def fixtures_root(self) -> Path:
        return REPO_ROOT / "fixtures"

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def install_tls_trust(settings: Settings | None = None) -> bool:
    """Route Python's TLS through the OS trust store.

    Returns True when the bridge was installed. Safe to call unconditionally: in
    replay mode nothing outbound happens anyway, and a missing ``truststore`` package
    degrades to a no-op rather than an error.
    """
    active = settings or get_settings()
    if not active.use_truststore:
        return False
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        return False
    return True
