"""Settings construction under a hostile environment.

These exist because of a deployment failure, not a hypothetical. Vercel creates
project environment variables from ``.env.example`` with blank values, so every
``AETHER_*`` key arrived present and empty. ``Settings()`` then rejected ''  for
the mode enum and the truststore boolean and the API could not be imported at
all, and the string-typed settings would have accepted '' silently — including
``engine_version``, which the reproducibility contract puts in every response
carrying a computed number.
"""

from __future__ import annotations

import pytest

from aether.config import Mode, Settings

#: Every key .env.example declares, blank — the exact shape the platform created.
BLANK_ENVIRONMENT = {
    "AETHER_MODE": "",
    "AETHER_USE_TRUSTSTORE": "",
    "AETHER_MODEL_ID": "",
    "AETHER_DB_URL": "",
    "AETHER_ENGINE_VERSION": "",
    "AETHER_CORS_ORIGINS": "",
    "ANTHROPIC_API_KEY": "",
}


@pytest.fixture
def blank_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in BLANK_ENVIRONMENT.items():
        monkeypatch.setenv(key, value)


def test_settings_construct_when_every_variable_is_blank(blank_environment: None) -> None:
    """An empty variable means unset. Before env_ignore_empty this raised ValidationError."""
    settings = Settings()

    assert settings.mode is Mode.REPLAY
    assert settings.use_truststore is True


def test_blank_variables_do_not_erase_the_reproducibility_fields(
    blank_environment: None,
) -> None:
    """engine_version and model_id travel in API responses; '' would be a silent corruption."""
    settings = Settings()

    assert settings.engine_version == "0.1.0"
    assert settings.model_id == "claude-opus-5"
    assert settings.db_url == "sqlite:///./aether.db"


def test_a_variable_that_is_actually_set_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ignoring empty values must not ignore real ones."""
    monkeypatch.setenv("AETHER_MODE", "live")
    monkeypatch.setenv("AETHER_ENGINE_VERSION", "9.9.9")

    settings = Settings()

    assert settings.mode is Mode.LIVE
    assert settings.engine_version == "9.9.9"
