from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from ottomandevice.ota.service import (
    OTA_STATUS_COMPLETED,
    OTA_STATUS_FAILED,
    OTA_STATUS_IDLE,
    OtaService,
)
from ottomandevice.ota.verifier import compute_sha256, compute_signature
from tests.unit.ota_test_helpers import make_firmware_zip

TEST_SECRET = "dev-ota-signing-secret-change-in-production"
PACKAGE_VERSION = "0.2.0"
PACKAGE_BYTES = make_firmware_zip(PACKAGE_VERSION)


@dataclass
class FakeQuery:
    data: list[dict[str, Any]] | None = None
    error: Any = None


class FakeTable:
    def __init__(self, responses: dict[str, FakeQuery]) -> None:
        self._responses = responses
        self._table_name = ""
        self._filters: dict[str, Any] = {}

    def select(self, *_args: Any, **_kwargs: Any) -> FakeTable:
        return self

    def eq(self, key: str, value: Any) -> FakeTable:
        self._filters[key] = value
        return self

    def order(self, *_args: Any, **_kwargs: Any) -> FakeTable:
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> FakeTable:
        return self

    def upsert(self, *_args: Any, **_kwargs: Any) -> FakeTable:
        return self

    def update(self, *_args: Any, **_kwargs: Any) -> FakeTable:
        return self

    def execute(self) -> FakeQuery:
        if self._table_name == "firmware_releases":
            return self._responses.get("releases", FakeQuery(data=[]))
        if self._table_name == "device_ota_status":
            return self._responses.get("status", FakeQuery(data=[]))
        if self._table_name == "devices_enhanced":
            return self._responses.get("devices", FakeQuery(data=[]))
        return FakeQuery(data=[])


class FakeStorageBucket:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def download(self, _path: str) -> bytes:
        return self._payload


class FakeSupabase:
    def __init__(self, responses: dict[str, FakeQuery], package_bytes: bytes) -> None:
        self._responses = responses
        bucket = FakeStorageBucket(package_bytes)
        self.storage = MagicMock()
        self.storage.from_.return_value = bucket

    def table(self, name: str) -> FakeTable:
        table = FakeTable(self._responses)
        table._table_name = name
        return table


def _published_package(*, sha256: str, signature: str) -> dict[str, Any]:
    return {
        "id": "release-1",
        "published": True,
        "firmware_packages": {
            "id": "pkg-1",
            "version": PACKAGE_VERSION,
            "file_name": "firmware.zip",
            "storage_path": f"{PACKAGE_VERSION}/firmware.zip",
            "sha256": sha256,
            "signature": signature,
            "file_size_bytes": len(PACKAGE_BYTES),
        },
    }


@pytest.fixture
def ota_service(tmp_path, monkeypatch: pytest.MonkeyPatch) -> OtaService:
    monkeypatch.setattr("ottomandevice.ota.service.get_device_id", lambda: "device-test")
    return OtaService(
        supabase=MagicMock(),
        current_version="0.1.0",
        download_dir=tmp_path / "downloads",
        active_dir=tmp_path / "active",
        backup_dir=tmp_path / "backup",
        signing_secret=TEST_SECRET,
        check_interval_seconds=60,
    )


def test_check_and_install_update_installs_valid_package(ota_service: OtaService, tmp_path) -> None:
    digest = compute_sha256(PACKAGE_BYTES)
    signature = compute_signature(digest, TEST_SECRET)
    ota_service._supabase = FakeSupabase(
        {"releases": FakeQuery(data=[_published_package(sha256=digest, signature=signature)])},
        PACKAGE_BYTES,
    )

    status = ota_service.check_and_install_update()

    assert status == OTA_STATUS_COMPLETED
    assert ota_service._current_version == PACKAGE_VERSION
    assert (tmp_path / "active" / "version.json").exists()
    assert (tmp_path / "backup" / "0.1.0" / "snapshot").exists()


def test_check_and_install_update_fails_for_invalid_hash(ota_service: OtaService) -> None:
    digest = compute_sha256(PACKAGE_BYTES)
    signature = compute_signature(digest, TEST_SECRET)
    ota_service._supabase = FakeSupabase(
        {
            "releases": FakeQuery(
                data=[_published_package(sha256="0" * 64, signature=signature)],
            )
        },
        PACKAGE_BYTES,
    )

    status = ota_service.check_and_install_update()

    assert status == OTA_STATUS_FAILED


def test_check_and_install_update_skips_when_up_to_date(ota_service: OtaService) -> None:
    digest = compute_sha256(PACKAGE_BYTES)
    signature = compute_signature(digest, TEST_SECRET)
    ota_service._current_version = PACKAGE_VERSION
    ota_service._supabase = FakeSupabase(
        {"releases": FakeQuery(data=[_published_package(sha256=digest, signature=signature)])},
        PACKAGE_BYTES,
    )

    status = ota_service.check_and_install_update()

    assert status == OTA_STATUS_IDLE


def test_check_and_install_update_rolls_back_corrupted_package(ota_service: OtaService, tmp_path) -> None:
    digest = compute_sha256(PACKAGE_BYTES)
    signature = compute_signature(digest, TEST_SECRET)
    active_dir = tmp_path / "active"
    active_dir.mkdir(parents=True)
    (active_dir / "version.json").write_text('{"version": "0.1.0"}', encoding="utf-8")

    corrupted_zip = make_firmware_zip(PACKAGE_VERSION, manifest_version="9.9.9")
    ota_service._supabase = FakeSupabase(
        {"releases": FakeQuery(data=[_published_package(sha256=digest, signature=signature)])},
        corrupted_zip,
    )

    status = ota_service.check_and_install_update()

    assert status == OTA_STATUS_FAILED
    assert ota_service._current_version == "0.1.0"
