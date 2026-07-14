from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ottomandevice.startup.health import (
    check_ota_configuration,
    check_remote_desktop_configuration,
    check_storage_bucket,
    start_service_safely,
)


def test_check_storage_bucket_passes_when_bucket_exists() -> None:
    supabase = MagicMock()
    supabase.storage.list_buckets.return_value = [{"name": "desktop-preview"}]

    status, message = check_storage_bucket(supabase, "desktop-preview")

    assert status == "PASS"
    assert "desktop-preview" in message


def test_check_storage_bucket_warns_when_bucket_missing() -> None:
    supabase = MagicMock()
    supabase.storage.list_buckets.return_value = [{"name": "screenshots"}]

    status, message = check_storage_bucket(supabase, "desktop-preview")

    assert status == "WARN"
    assert "missing" in message


def test_check_remote_desktop_configuration_states() -> None:
    assert check_remote_desktop_configuration("secret")[0] == "PASS"
    assert check_remote_desktop_configuration("")[0] == "WARN"


def test_check_ota_configuration_states() -> None:
    assert check_ota_configuration("secret")[0] == "PASS"
    assert check_ota_configuration("")[0] == "DISABLED"


def test_start_service_safely_disables_optional_service_on_failure() -> None:
    class FailingService:
        def start(self) -> None:
            raise RuntimeError("boom")

    status, message = start_service_safely(FailingService(), "Desktop Stream", required=False)

    assert status == "WARN"
    assert "disabled" in message


def test_start_service_safely_raises_for_required_service() -> None:
    class FailingService:
        def start(self) -> None:
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        start_service_safely(FailingService(), "Heartbeat", required=True)
