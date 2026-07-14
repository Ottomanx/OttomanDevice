"""Backward-compatible device registration shims."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from supabase import Client

from ottomandevice.device.identity import DeviceIdentity, get_device_uuid
from ottomandevice.paths import PROJECT_ROOT

DEVICE_ID_PATH = PROJECT_ROOT / "data" / "device_id"


def load_or_create_device_id() -> str:
    return get_device_uuid()


def get_device_id() -> str:
    return get_device_uuid()


def _lookup_existing_device_id(supabase: Client, computer_name: str) -> str | None:
    try:
        response = (
            supabase.table("devices_enhanced")
            .select("device_id")
            .eq("computer_name", computer_name)
            .order("last_online_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = cast(list[dict[str, Any]], response.data or [])
        if rows:
            device_id = rows[0].get("device_id")
            if device_id:
                return str(device_id)
    except Exception:
        return None
    return None


def resolve_device_id(
    supabase: Client,
    computer_name: str | None = None,
    path: Path | None = None,
) -> str:
    if path is None:
        return DeviceIdentity.load().device_uuid

    resolved_path = path
    if resolved_path.exists():
        device_id = resolved_path.read_text(encoding="utf-8").strip()
        if device_id:
            return device_id

    name = computer_name or __import__("platform").node()
    existing_id = _lookup_existing_device_id(supabase, name)
    if existing_id:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(existing_id, encoding="utf-8")
        return existing_id

    import uuid

    device_id = str(uuid.uuid4())
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(device_id, encoding="utf-8")
    return device_id


def register_device(supabase, device=None) -> None:
    from ottomandevice.device.certificate import DeviceCertificate
    from ottomandevice.device.registry import DeviceRegistry

    identity = DeviceIdentity.load()
    certificate = DeviceCertificate.ensure(identity.device_uuid)
    registry = DeviceRegistry(
        supabase=supabase,
        identity=identity,
        certificate=certificate,
    )
    registry.register()


class Device:
    def __init__(self, device_id: str | None = None) -> None:
        self._identity = DeviceIdentity.load()

    @property
    def device_id(self) -> str:
        return self._identity.device_uuid

    def to_record(self) -> dict:
        from ottomandevice.device.profile import DeviceProfile

        profile = DeviceProfile.collect(self._identity)
        return {
            "device_id": profile.device_uuid,
            "computer_name": profile.hostname,
            "operating_system": profile.os,
            "python_version": __import__("platform").python_version(),
            "firmware_version": profile.application_version,
            "status": "ONLINE",
        }
