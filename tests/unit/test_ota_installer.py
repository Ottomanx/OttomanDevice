from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ottomandevice.ota.installer import (
    INSTALL_LOCK_NAME,
    OtaCorruptedPackageError,
    OtaInstallError,
    OtaInterruptedInstallError,
    create_backup,
    detect_interrupted_install,
    install_verified_package,
    read_installed_version,
    rollback_from_backup,
    validate_package_archive,
)
from tests.unit.ota_test_helpers import make_firmware_zip

PACKAGE_VERSION = "0.2.0"


def test_successful_install(tmp_path: Path) -> None:
    package_path = tmp_path / "firmware.zip"
    active_dir = tmp_path / "active"
    backup_root = tmp_path / "backup"
    package_path.write_bytes(make_firmware_zip(PACKAGE_VERSION))

    backup = create_backup(active_dir, backup_root, "0.1.0")
    result = install_verified_package(
        package_path,
        active_dir,
        backup,
        target_version=PACKAGE_VERSION,
    )

    assert result.target_version == PACKAGE_VERSION
    assert read_installed_version(active_dir, "0.1.0") == PACKAGE_VERSION
    assert (active_dir / "payload.txt").exists()
    assert (backup_root / "0.1.0" / "snapshot").exists()


def test_failed_install_preserves_backup_for_rollback(tmp_path: Path) -> None:
    package_path = tmp_path / "invalid.zip"
    active_dir = tmp_path / "active"
    backup_root = tmp_path / "backup"
    active_dir.mkdir(parents=True)
    (active_dir / "version.json").write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
    package_path.write_bytes(b"not-a-valid-zip")

    backup = create_backup(active_dir, backup_root, "0.1.0")

    with pytest.raises(OtaInstallError):
        install_verified_package(
            package_path,
            active_dir,
            backup,
            target_version=PACKAGE_VERSION,
        )

    restored_version = rollback_from_backup(active_dir, backup)
    assert restored_version == "0.1.0"
    assert read_installed_version(active_dir, "0.0.0") == "0.1.0"


def test_rollback_restores_previous_firmware(tmp_path: Path) -> None:
    active_dir = tmp_path / "active"
    backup_root = tmp_path / "backup"
    active_dir.mkdir(parents=True)
    (active_dir / "version.json").write_text(json.dumps({"version": "0.1.0"}), encoding="utf-8")
    (active_dir / "payload.txt").write_text("old", encoding="utf-8")

    backup = create_backup(active_dir, backup_root, "0.1.0")
    shutil.rmtree(active_dir)
    active_dir.mkdir(parents=True)
    (active_dir / "version.json").write_text(json.dumps({"version": "0.2.0"}), encoding="utf-8")
    (active_dir / "payload.txt").write_text("broken", encoding="utf-8")

    restored_version = rollback_from_backup(active_dir, backup)

    assert restored_version == "0.1.0"
    assert read_installed_version(active_dir, "0.0.0") == "0.1.0"
    assert (active_dir / "payload.txt").read_text(encoding="utf-8") == "old"


def test_corrupted_package_rejected(tmp_path: Path) -> None:
    package_path = tmp_path / "firmware.zip"
    package_path.write_bytes(b"corrupted")

    with pytest.raises(OtaCorruptedPackageError):
        validate_package_archive(package_path, PACKAGE_VERSION)

    package_path.write_bytes(make_firmware_zip(PACKAGE_VERSION, manifest_version="9.9.9"))
    with pytest.raises(OtaCorruptedPackageError):
        validate_package_archive(package_path, PACKAGE_VERSION)


def test_interrupted_install_detected(tmp_path: Path) -> None:
    active_dir = tmp_path / "active"
    active_dir.mkdir(parents=True)
    lock_path = active_dir.parent / INSTALL_LOCK_NAME
    lock_path.write_text("installing", encoding="utf-8")

    assert detect_interrupted_install(active_dir) is True

    package_path = tmp_path / "firmware.zip"
    package_path.write_bytes(make_firmware_zip(PACKAGE_VERSION))
    backup = create_backup(active_dir, tmp_path / "backup", "0.1.0")

    with pytest.raises(OtaInterruptedInstallError):
        install_verified_package(
            package_path,
            active_dir,
            backup,
            target_version=PACKAGE_VERSION,
        )
