import platform
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, cast

from supabase import Client

from ottomandevice.config import settings
from ottomandevice.paths import PROJECT_ROOT

DEVICE_ID_PATH = PROJECT_ROOT / "data" / "device_id"
FIRMWARE_VERSION = settings.firmware.version


class DeviceStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


def load_or_create_device_id(path: Path = DEVICE_ID_PATH) -> str:
    if path.exists():
        device_id = path.read_text(encoding="utf-8").strip()
        if device_id:
            return device_id

    device_id = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(device_id, encoding="utf-8")
    return device_id


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
    resolved_path = path or DEVICE_ID_PATH
    if resolved_path.exists():
        device_id = resolved_path.read_text(encoding="utf-8").strip()
        if device_id:
            return device_id

    name = computer_name or platform.node()
    existing_id = _lookup_existing_device_id(supabase, name)
    if existing_id:
        resolved_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_path.write_text(existing_id, encoding="utf-8")
        return existing_id

    device_id = str(uuid.uuid4())
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    resolved_path.write_text(device_id, encoding="utf-8")
    return device_id


def get_device_id(path: Path = DEVICE_ID_PATH) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Device ID file not found: {path}")

    device_id = path.read_text(encoding="utf-8").strip()
    if not device_id:
        raise ValueError(f"Device ID file is empty: {path}")

    return device_id


@dataclass(frozen=True)
class Device:
    device_id: str = field(default_factory=load_or_create_device_id)
    computer_name: str = field(default_factory=platform.node)
    operating_system: str = field(default_factory=platform.platform)
    python_version: str = field(default_factory=platform.python_version)
    firmware_version: str = FIRMWARE_VERSION
    status: DeviceStatus = DeviceStatus.ONLINE

    def to_record(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "computer_name": self.computer_name,
            "operating_system": self.operating_system,
            "python_version": self.python_version,
            "firmware_version": self.firmware_version,
            "status": self.status.value,
            "last_online_at": datetime.now(timezone.utc).isoformat(),
        }


def register_device(supabase: Client, device: Device | None = None) -> None:
    if device is None:
        computer_name = platform.node()
        device_id = resolve_device_id(supabase, computer_name)
        device = Device(device_id=device_id)
    record = device.to_record()
    supabase.table("devices_enhanced").upsert(record, on_conflict="device_id").execute()
