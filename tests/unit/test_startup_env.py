from __future__ import annotations

import pytest

from ottomandevice.startup.env import validate_environment


def test_validate_environment_requires_supabase_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    monkeypatch.delenv("REMOTE_DESKTOP_JWT_SECRET", raising=False)
    monkeypatch.delenv("OTA_SIGNING_SECRET", raising=False)

    result = validate_environment()

    assert result.fatal is True
    assert any("SUPABASE_URL" in message for message in result.errors)
    assert any("SUPABASE_ANON_KEY" in message for message in result.errors)


def test_validate_environment_warns_for_optional_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.delenv("REMOTE_DESKTOP_JWT_SECRET", raising=False)
    monkeypatch.delenv("OTA_SIGNING_SECRET", raising=False)

    result = validate_environment()

    assert result.fatal is False
    assert any("REMOTE_DESKTOP_JWT_SECRET" in message for message in result.warnings)
    assert any("OTA_SIGNING_SECRET" in message for message in result.warnings)


def test_validate_environment_passes_with_all_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("REMOTE_DESKTOP_JWT_SECRET", "jwt-secret")
    monkeypatch.setenv("OTA_SIGNING_SECRET", "ota-secret")

    result = validate_environment()

    assert result.fatal is False
    assert result.errors == []
    assert result.warnings == []
