from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from supabase import Client, create_client

from ottomandevice.camera import CameraInfo, CameraService
from ottomandevice.config import settings
from ottomandevice.runtime import register_device

HealthStatus = Literal["PASS", "WARN", "FAIL", "DISABLED"]


@dataclass
class HealthReport:
    checks: dict[str, HealthStatus] = field(default_factory=dict)
    messages: dict[str, str] = field(default_factory=dict)

    def set(self, name: str, status: HealthStatus, message: str = "") -> None:
        self.checks[name] = status
        if message:
            self.messages[name] = message

    def get(self, name: str) -> HealthStatus:
        return self.checks.get(name, "WARN")

    def merge(self, other: HealthReport) -> None:
        self.checks.update(other.checks)
        self.messages.update(other.messages)


def check_supabase_connection(url: str, key: str) -> tuple[Client | None, HealthStatus, str]:
    try:
        client = create_client(url, key)
        client.table("devices_enhanced").select("id").limit(1).execute()
        return client, "PASS", "Connected"
    except Exception as exc:
        return None, "FAIL", str(exc)


def check_device_registration(supabase: Client) -> tuple[HealthStatus, str]:
    try:
        register_device(supabase)
        return "PASS", "Registered"
    except Exception as exc:
        return "FAIL", str(exc)


def _list_bucket_names(supabase: Client) -> set[str]:
    response = supabase.storage.list_buckets()
    buckets = response if isinstance(response, list) else []
    names: set[str] = set()

    for bucket in buckets:
        if isinstance(bucket, dict):
            name = bucket.get("name") or bucket.get("id")
        else:
            name = getattr(bucket, "name", None) or getattr(bucket, "id", None)
        if name:
            names.add(str(name))

    return names


def check_storage_bucket(supabase: Client, bucket_name: str) -> tuple[HealthStatus, str]:
    try:
        available = _list_bucket_names(supabase)
        if bucket_name in available:
            return "PASS", f"Bucket '{bucket_name}' available"
        return "WARN", f"Bucket '{bucket_name}' missing"
    except Exception as exc:
        return "WARN", f"Bucket '{bucket_name}' check failed: {exc}"


def check_camera() -> tuple[HealthStatus, str, CameraInfo | None]:
    try:
        camera_info = CameraService().run_camera_check()
    except Exception as exc:
        return "WARN", f"Camera check failed: {exc}", None

    if camera_info is None:
        return "WARN", "Camera not detected", None

    return (
        "PASS",
        f"Camera index {camera_info.index} ({camera_info.width}x{camera_info.height})",
        camera_info,
    )


def check_remote_desktop_configuration(jwt_secret: str) -> tuple[HealthStatus, str]:
    if jwt_secret.strip():
        return "PASS", "JWT secret configured"
    return "WARN", "JWT secret not configured"


def check_ota_configuration(ota_secret: str) -> tuple[HealthStatus, str]:
    if ota_secret.strip():
        return "PASS", "OTA signing secret configured"
    return "DISABLED", "OTA signing secret not configured"


def run_startup_health_checks(
    *,
    supabase: Client,
    jwt_secret: str,
    ota_secret: str,
) -> HealthReport:
    report = HealthReport()

    registration_status, registration_message = check_device_registration(supabase)
    report.set("device_registration", registration_status, registration_message)

    bucket_checks = {
        "bucket_screenshots": settings.storage.screenshots_bucket,
        "bucket_desktop_preview": settings.storage.desktop_bucket,
        "bucket_firmware": settings.ota.firmware_bucket,
    }

    for check_name, bucket_name in bucket_checks.items():
        status, message = check_storage_bucket(supabase, bucket_name)
        report.set(check_name, status, message)

    camera_status, camera_message, _camera_info = check_camera()
    report.set("camera", camera_status, camera_message)

    remote_status, remote_message = check_remote_desktop_configuration(jwt_secret)
    report.set("remote_desktop_config", remote_status, remote_message)

    ota_status, ota_message = check_ota_configuration(ota_secret)
    report.set("ota_config", ota_status, ota_message)

    return report


def start_service_safely(service: Any, name: str, *, required: bool) -> tuple[HealthStatus, str]:
    start = getattr(service, "start", None)
    if not callable(start):
        return "WARN", f"{name} has no start() method"

    try:
        start()
        return "PASS", f"{name} started"
    except Exception as exc:
        if required:
            raise
        return "WARN", f"{name} disabled: {exc}"
