from __future__ import annotations

import platform
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast

from supabase import Client

from ottomandevice.core.event_bus import (
    DeviceProfileUpdated,
    DeviceRegistered,
    DeviceRegistrationFailed,
    EventBus,
)
from ottomandevice.core.exceptions import DeviceIdentityError
from ottomandevice.device.certificate import DeviceCertificate
from ottomandevice.device.identity import DeviceIdentity
from ottomandevice.device.profile import DeviceProfile
from ottomandevice.device.profile import APPLICATION_VERSION


@dataclass(frozen=True)
class RegistrationResult:
    """Outcome of a device registration attempt."""

    device_uuid: str
    is_new: bool
    installation_id: str


class DeviceRegistry:
    """Thread-safe cloud registration and profile synchronization."""

    _lock = threading.RLock()

    def __init__(
        self,
        *,
        supabase: Client,
        identity: DeviceIdentity,
        certificate: DeviceCertificate,
        event_bus: EventBus | None = None,
    ) -> None:
        self._supabase = supabase
        self._identity = identity
        self._certificate = certificate
        self._event_bus = event_bus or EventBus.get_instance()

    @property
    def identity(self) -> DeviceIdentity:
        return self._identity

    @property
    def certificate(self) -> DeviceCertificate:
        return self._certificate

    def register(self) -> RegistrationResult:
        """Register the device with the cloud backend, reusing identity when present."""
        with self._lock:
            try:
                is_new = not self._cloud_device_exists(self._identity.device_uuid)
                record = self._build_registration_record(is_new=is_new)
                self._supabase.table("devices_enhanced").upsert(
                    record,
                    on_conflict="device_id",
                ).execute()

                result = RegistrationResult(
                    device_uuid=self._identity.device_uuid,
                    is_new=is_new,
                    installation_id=self._identity.installation_id,
                )
                self._publish(
                    DeviceRegistered(
                        device_uuid=result.device_uuid,
                        installation_id=result.installation_id,
                        is_new=result.is_new,
                    )
                )
                return result
            except Exception as exc:
                self._publish(
                    DeviceRegistrationFailed(
                        device_uuid=self._identity.device_uuid,
                        error=str(exc),
                    )
                )
                raise DeviceIdentityError(f"Device registration failed: {exc}") from exc

    def update_profile(self, profile: DeviceProfile) -> None:
        """Synchronize the runtime device profile to the cloud backend."""
        with self._lock:
            try:
                payload = {
                    "device_id": profile.device_uuid,
                    "hostname": profile.hostname,
                    "operating_system": profile.os,
                    "computer_name": profile.hostname,
                    "firmware_version": profile.application_version,
                    "architecture": profile.architecture,
                    "cpu_model": profile.cpu,
                    "ram_total_mb": profile.ram_mb,
                    "application_version": profile.application_version,
                    "runtime_version": profile.runtime_version,
                    "device_profile": profile.to_dict(),
                    "last_online_at": datetime.now(timezone.utc).isoformat(),
                }
                self._supabase.table("devices_enhanced").upsert(
                    payload,
                    on_conflict="device_id",
                ).execute()
                self._publish(
                    DeviceProfileUpdated(
                        device_uuid=profile.device_uuid,
                        plugin_count=len(profile.plugins),
                    )
                )
            except Exception as exc:
                raise DeviceIdentityError(f"Device profile update failed: {exc}") from exc

    def _cloud_device_exists(self, device_uuid: str) -> bool:
        response = (
            self._supabase.table("devices_enhanced")
            .select("device_id")
            .eq("device_id", device_uuid)
            .limit(1)
            .execute()
        )
        rows = cast(list[dict[str, Any]], response.data or [])
        return bool(rows)

    def _build_registration_record(self, *, is_new: bool) -> dict[str, Any]:
        timestamp = datetime.now(timezone.utc).isoformat()
        signature = self._certificate.registration_signature(
            installation_id=self._identity.installation_id,
            timestamp=timestamp,
        )
        return {
            "device_id": self._identity.device_uuid,
            "installation_id": self._identity.installation_id,
            "computer_name": self._identity.hostname,
            "hostname": self._identity.hostname,
            "operating_system": platform.platform(),
            "python_version": platform.python_version(),
            "firmware_version": APPLICATION_VERSION,
            "status": "ONLINE",
            "certificate_fingerprint": self._certificate.fingerprint,
            "first_boot_timestamp": self._identity.first_boot_timestamp.isoformat(),
            "registration_signature": signature,
            "last_online_at": timestamp,
        }

    def _publish(self, event: Any) -> None:
        self._event_bus.publish(event)
