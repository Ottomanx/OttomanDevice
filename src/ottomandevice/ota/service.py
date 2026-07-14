from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from supabase import Client

from ottomandevice.config import settings
from ottomandevice.logging import get_logger
from ottomandevice.ota.installer import (
    InstallBackup,
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
from ottomandevice.ota.rollback import build_rollback_manifest, write_rollback_manifest
from ottomandevice.ota.verifier import is_newer_version, verify_sha256, verify_signature
from ottomandevice.paths import PROJECT_ROOT
from ottomandevice.runtime import get_device_id

logger = get_logger("ota")

OTA_STATUS_IDLE = "idle"
OTA_STATUS_CHECKING = "checking"
OTA_STATUS_DOWNLOADING = "downloading"
OTA_STATUS_VERIFYING = "verifying"
OTA_STATUS_INSTALLING = "installing"
OTA_STATUS_COMPLETED = "completed"
OTA_STATUS_FAILED = "failed"
OTA_STATUS_ROLLBACK = "rollback"

STATUS_PROGRESS = {
    OTA_STATUS_IDLE: 0,
    OTA_STATUS_CHECKING: 5,
    OTA_STATUS_DOWNLOADING: 20,
    OTA_STATUS_VERIFYING: 40,
    OTA_STATUS_INSTALLING: 70,
    OTA_STATUS_ROLLBACK: 50,
    OTA_STATUS_COMPLETED: 100,
    OTA_STATUS_FAILED: 0,
}


@dataclass(frozen=True)
class FirmwarePackage:
    id: str
    version: str
    file_name: str
    storage_path: str
    sha256: str
    signature: str
    file_size_bytes: int


class OtaService:
    def __init__(
        self,
        supabase: Client,
        current_version: str | None = None,
        check_interval_seconds: int | None = None,
        download_dir: Path | None = None,
        active_dir: Path | None = None,
        backup_dir: Path | None = None,
        firmware_bucket: str | None = None,
        signing_secret: str | None = None,
    ) -> None:
        self._supabase = supabase
        self._current_version = current_version or settings.firmware.version
        self._check_interval_seconds = check_interval_seconds or settings.ota.check_interval
        self._download_dir = download_dir or (PROJECT_ROOT / settings.ota.download_dir)
        self._active_dir = active_dir or (PROJECT_ROOT / settings.ota.active_dir)
        self._backup_dir = backup_dir or (PROJECT_ROOT / settings.ota.backup_dir)
        self._firmware_bucket = firmware_bucket or settings.ota.firmware_bucket
        self._signing_secret = signing_secret or self._load_signing_secret()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_backup: InstallBackup | None = None

    def _load_signing_secret(self) -> str:
        env_name = settings.ota.signing_secret_env
        secret = os.getenv(env_name)
        if not secret:
            raise RuntimeError(f"Missing OTA signing secret env var: {env_name}")
        return secret

    def _fetch_latest_published_package(self) -> FirmwarePackage | None:
        response = (
            self._supabase.table("firmware_releases")
            .select(
                "id, published, firmware_packages(id, version, file_name, storage_path, sha256, signature, file_size_bytes)"
            )
            .eq("published", True)
            .order("published_at", desc=True)
            .limit(1)
            .execute()
        )

        rows = cast(list[dict[str, Any]], response.data or [])
        if not rows:
            return None

        package_data = rows[0].get("firmware_packages")
        if not package_data:
            return None

        if isinstance(package_data, list):
            if not package_data:
                return None
            package_data = package_data[0]

        return FirmwarePackage(
            id=str(package_data["id"]),
            version=str(package_data["version"]),
            file_name=str(package_data["file_name"]),
            storage_path=str(package_data["storage_path"]),
            sha256=str(package_data["sha256"]),
            signature=str(package_data["signature"]),
            file_size_bytes=int(package_data["file_size_bytes"]),
        )

    def _report_status(
        self,
        *,
        status: str,
        target_version: str | None = None,
        package_id: str | None = None,
        message: str | None = None,
        progress: int | None = None,
    ) -> None:
        device_id = get_device_id()
        payload = {
            "device_id": device_id,
            "current_version": self._current_version,
            "target_version": target_version,
            "status": status,
            "message": message,
            "package_id": package_id,
            "progress": progress if progress is not None else STATUS_PROGRESS.get(status, 0),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        self._supabase.table("device_ota_status").upsert(payload, on_conflict="device_id").execute()

    def _download_package(self, package: FirmwarePackage) -> Path:
        self._download_dir.mkdir(parents=True, exist_ok=True)
        destination = self._download_dir / package.version / package.file_name

        response = self._supabase.storage.from_(self._firmware_bucket).download(package.storage_path)
        file_bytes = response if isinstance(response, bytes) else bytes(response)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(file_bytes)
        return destination

    def _update_device_firmware_version(self, version: str) -> None:
        device_id = get_device_id()
        self._supabase.table("devices_enhanced").update({"firmware_version": version}).eq(
            "device_id",
            device_id,
        ).execute()
        self._current_version = version

    def _handle_install_failure(
        self,
        package: FirmwarePackage,
        backup: InstallBackup | None,
        reason: str,
    ) -> str:
        if backup is not None:
            self._report_status(
                status=OTA_STATUS_ROLLBACK,
                target_version=package.version,
                package_id=package.id,
                message="Install failed; rolling back to previous firmware",
            )
            try:
                restored_version = rollback_from_backup(self._active_dir, backup)
                self._current_version = restored_version
                self._update_device_firmware_version(restored_version)
                self._report_status(
                    status=OTA_STATUS_FAILED,
                    target_version=package.version,
                    package_id=package.id,
                    message=f"Install failed and rolled back to {restored_version}: {reason}",
                )
                return OTA_STATUS_FAILED
            except Exception as rollback_exc:
                logger.exception("OTA rollback failed")
                self._report_status(
                    status=OTA_STATUS_FAILED,
                    target_version=package.version,
                    package_id=package.id,
                    message=f"Install failed and rollback failed: {rollback_exc}",
                )
                return OTA_STATUS_FAILED

        self._report_status(
            status=OTA_STATUS_FAILED,
            target_version=package.version,
            package_id=package.id,
            message=reason,
        )
        return OTA_STATUS_FAILED

    def check_and_install_update(self) -> str:
        self._report_status(status=OTA_STATUS_CHECKING)

        try:
            if detect_interrupted_install(self._active_dir):
                interrupted_backup = self._last_backup
                if interrupted_backup is not None:
                    self._report_status(
                        status=OTA_STATUS_ROLLBACK,
                        message="Recovering from interrupted OTA install",
                    )
                    restored_version = rollback_from_backup(self._active_dir, interrupted_backup)
                    self._current_version = restored_version
                    self._update_device_firmware_version(restored_version)
                    self._report_status(
                        status=OTA_STATUS_FAILED,
                        message=f"Interrupted install recovered; rolled back to {restored_version}",
                    )
                    return OTA_STATUS_FAILED

            package = self._fetch_latest_published_package()
            if package is None:
                self._report_status(status=OTA_STATUS_IDLE, message="No published firmware release")
                return OTA_STATUS_IDLE

            if not is_newer_version(self._current_version, package.version):
                self._report_status(
                    status=OTA_STATUS_IDLE,
                    target_version=package.version,
                    message="Device firmware is up to date",
                )
                return OTA_STATUS_IDLE

            self._report_status(
                status=OTA_STATUS_DOWNLOADING,
                target_version=package.version,
                package_id=package.id,
                message="Downloading firmware package",
            )
            local_path = self._download_package(package)
            file_bytes = local_path.read_bytes()

            self._report_status(
                status=OTA_STATUS_VERIFYING,
                target_version=package.version,
                package_id=package.id,
                message="Verifying firmware package",
            )

            if not verify_sha256(file_bytes, package.sha256):
                return self._handle_install_failure(package, None, "SHA256 verification failed")

            if not verify_signature(package.sha256, package.signature, self._signing_secret):
                return self._handle_install_failure(package, None, "Signature verification failed")

            try:
                validate_package_archive(local_path, package.version)
            except OtaCorruptedPackageError as exc:
                return self._handle_install_failure(package, None, str(exc))

            manifest = build_rollback_manifest(
                current_version=self._current_version,
                target_version=package.version,
                package_id=package.id,
                package_sha256=package.sha256,
                package_signature=package.signature,
                storage_path=package.storage_path,
            )
            write_rollback_manifest(self._download_dir, manifest)

            self._report_status(
                status=OTA_STATUS_INSTALLING,
                target_version=package.version,
                package_id=package.id,
                message="Installing verified firmware package",
            )

            install_backup = create_backup(self._active_dir, self._backup_dir, self._current_version)
            self._last_backup = install_backup
            try:
                install_result = install_verified_package(
                    local_path,
                    self._active_dir,
                    install_backup,
                    target_version=package.version,
                )
            except (OtaInstallError, OtaInterruptedInstallError) as exc:
                return self._handle_install_failure(package, install_backup, str(exc))

            installed_version = read_installed_version(install_result.active_dir, package.version)
            self._current_version = installed_version
            self._update_device_firmware_version(installed_version)

            self._report_status(
                status=OTA_STATUS_COMPLETED,
                target_version=installed_version,
                package_id=package.id,
                message=f"Firmware {installed_version} installed successfully",
            )
            logger.info("OTA install completed for version %s", installed_version)
            return OTA_STATUS_COMPLETED
        except Exception as exc:
            logger.exception("OTA install failed")
            self._report_status(status=OTA_STATUS_FAILED, message=str(exc))
            return OTA_STATUS_FAILED

    def check_and_prepare_update(self) -> str:
        return self.check_and_install_update()

    def _run(self) -> None:
        while not self._stop_event.wait(self._check_interval_seconds):
            try:
                self.check_and_install_update()
            except Exception:
                logger.exception("OTA service iteration failed")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="ota-service", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._check_interval_seconds + 1)

    def join(self) -> None:
        if self._thread:
            self._thread.join()
