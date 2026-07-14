from __future__ import annotations

import json
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path


class OtaInstallError(Exception):
    pass


class OtaCorruptedPackageError(OtaInstallError):
    pass


class OtaInterruptedInstallError(OtaInstallError):
    pass


@dataclass(frozen=True)
class InstallBackup:
    backup_path: Path
    previous_version: str


@dataclass(frozen=True)
class InstallResult:
    target_version: str
    active_dir: Path
    backup: InstallBackup


INSTALL_LOCK_NAME = ".install.lock"
MANIFEST_NAME = "manifest.json"


def validate_package_archive(package_path: Path, expected_version: str) -> None:
    if not zipfile.is_zipfile(package_path):
        raise OtaCorruptedPackageError("Firmware package is not a valid ZIP archive")

    with zipfile.ZipFile(package_path) as archive:
        if MANIFEST_NAME not in archive.namelist():
            raise OtaCorruptedPackageError("Firmware package is missing manifest.json")

        manifest = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        package_version = str(manifest.get("version", "")).strip()
        if package_version != expected_version:
            raise OtaCorruptedPackageError(
                f"Firmware manifest version mismatch: expected {expected_version}, got {package_version or 'unknown'}"
            )


def detect_interrupted_install(active_dir: Path) -> bool:
    lock_path = active_dir.parent / INSTALL_LOCK_NAME
    return lock_path.exists()


def create_backup(active_dir: Path, backup_root: Path, current_version: str) -> InstallBackup:
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / current_version / "snapshot"
    if backup_path.exists():
        shutil.rmtree(backup_path)

    if active_dir.exists():
        shutil.copytree(active_dir, backup_path)
    else:
        backup_path.mkdir(parents=True, exist_ok=True)
        version_file = backup_path / "version.json"
        version_file.write_text(
            json.dumps({"version": current_version}, indent=2),
            encoding="utf-8",
        )

    return InstallBackup(backup_path=backup_path, previous_version=current_version)


def install_verified_package(
    package_path: Path,
    active_dir: Path,
    backup: InstallBackup,
    *,
    target_version: str,
) -> InstallResult:
    if detect_interrupted_install(active_dir):
        raise OtaInterruptedInstallError("Detected interrupted OTA install")

    validate_package_archive(package_path, target_version)

    install_root = active_dir.parent
    install_root.mkdir(parents=True, exist_ok=True)
    lock_path = install_root / INSTALL_LOCK_NAME
    staging_dir = install_root / "staging" / target_version

    try:
        lock_path.write_text("installing", encoding="utf-8")

        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(package_path) as archive:
            archive.extractall(staging_dir)

        if active_dir.exists():
            shutil.rmtree(active_dir)

        shutil.copytree(staging_dir, active_dir)
        version_file = active_dir / "version.json"
        version_file.write_text(
            json.dumps({"version": target_version}, indent=2),
            encoding="utf-8",
        )

        return InstallResult(
            target_version=target_version,
            active_dir=active_dir,
            backup=backup,
        )
    except OtaInstallError:
        raise
    except Exception as exc:
        raise OtaInstallError(str(exc)) from exc
    finally:
        lock_path.unlink(missing_ok=True)
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def rollback_from_backup(active_dir: Path, backup: InstallBackup) -> str:
    if active_dir.exists():
        shutil.rmtree(active_dir)

    if backup.backup_path.exists():
        shutil.copytree(backup.backup_path, active_dir)
    else:
        active_dir.mkdir(parents=True, exist_ok=True)
        (active_dir / "version.json").write_text(
            json.dumps({"version": backup.previous_version}, indent=2),
            encoding="utf-8",
        )

    return backup.previous_version


def read_installed_version(active_dir: Path, fallback_version: str) -> str:
    version_file = active_dir / "version.json"
    if not version_file.exists():
        return fallback_version

    payload = json.loads(version_file.read_text(encoding="utf-8"))
    version = str(payload.get("version", "")).strip()
    return version or fallback_version
