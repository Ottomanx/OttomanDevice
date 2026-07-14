from __future__ import annotations

import json
import platform
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ottomandevice.core.exceptions import DeviceIdentityError
from ottomandevice.paths import PROJECT_ROOT

DEVICE_JSON_PATH = PROJECT_ROOT / "data" / "device.json"
LEGACY_DEVICE_ID_PATH = PROJECT_ROOT / "data" / "device_id"
_STORE_LOCK = threading.RLock()


@dataclass(frozen=True)
class DeviceIdentityRecord:
    """Persisted local device identity."""

    device_uuid: str
    installation_id: str
    first_boot_timestamp: str
    hostname: str
    certificate_fingerprint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeviceIdentity:
    """Thread-safe local device identity store backed by data/device.json."""

    def __init__(self, record: DeviceIdentityRecord) -> None:
        self._record = record

    @property
    def device_uuid(self) -> str:
        return self._record.device_uuid

    @property
    def installation_id(self) -> str:
        return self._record.installation_id

    @property
    def first_boot_timestamp(self) -> datetime:
        return datetime.fromisoformat(self._record.first_boot_timestamp)

    @property
    def hostname(self) -> str:
        return self._record.hostname

    @property
    def certificate_fingerprint(self) -> str | None:
        return self._record.certificate_fingerprint

    @property
    def is_first_boot(self) -> bool:
        return False

    @classmethod
    def load(cls, *, store_path: Path | None = None) -> DeviceIdentity:
        """Load identity from disk or create a new one on first boot."""
        path = store_path or DEVICE_JSON_PATH
        with _STORE_LOCK:
            if path.exists():
                return cls._load_existing(path)
            legacy_id = cls._read_legacy_device_id()
            if legacy_id is not None:
                return cls._create_from_legacy(path, legacy_id)
            return cls._create_new(path)

    @classmethod
    def from_record(cls, record: DeviceIdentityRecord) -> DeviceIdentity:
        return cls(record)

    def with_certificate_fingerprint(self, fingerprint: str) -> DeviceIdentity:
        updated = DeviceIdentityRecord(
            device_uuid=self._record.device_uuid,
            installation_id=self._record.installation_id,
            first_boot_timestamp=self._record.first_boot_timestamp,
            hostname=self._record.hostname,
            certificate_fingerprint=fingerprint,
        )
        return DeviceIdentity(updated)

    def persist(self, *, store_path: Path | None = None) -> None:
        """Persist the current identity record to disk."""
        path = store_path or DEVICE_JSON_PATH
        with _STORE_LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self._record.to_dict(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    @staticmethod
    def _load_existing(path: Path) -> DeviceIdentity:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DeviceIdentityError(f"Unable to read identity store: {path}") from exc

        try:
            record = DeviceIdentityRecord(
                device_uuid=str(payload["device_uuid"]),
                installation_id=str(payload["installation_id"]),
                first_boot_timestamp=str(payload["first_boot_timestamp"]),
                hostname=str(payload["hostname"]),
                certificate_fingerprint=payload.get("certificate_fingerprint"),
            )
        except KeyError as exc:
            raise DeviceIdentityError(f"Identity store missing required field: {exc}") from exc

        if not record.device_uuid or not record.installation_id:
            raise DeviceIdentityError("Identity store contains empty identifiers")

        return DeviceIdentity(record)

    @classmethod
    def _create_new(cls, path: Path) -> DeviceIdentity:
        now = datetime.now(timezone.utc)
        record = DeviceIdentityRecord(
            device_uuid=str(uuid.uuid4()),
            installation_id=str(uuid.uuid4()),
            first_boot_timestamp=now.isoformat(),
            hostname=platform.node(),
        )
        identity = cls(record)
        identity.persist(store_path=path)
        return identity

    @classmethod
    def _create_from_legacy(cls, path: Path, legacy_id: str) -> DeviceIdentity:
        now = datetime.now(timezone.utc)
        record = DeviceIdentityRecord(
            device_uuid=legacy_id,
            installation_id=str(uuid.uuid4()),
            first_boot_timestamp=now.isoformat(),
            hostname=platform.node(),
        )
        identity = cls(record)
        identity.persist(store_path=path)
        return identity

    @staticmethod
    def _read_legacy_device_id() -> str | None:
        if not LEGACY_DEVICE_ID_PATH.exists():
            return None
        device_id = LEGACY_DEVICE_ID_PATH.read_text(encoding="utf-8").strip()
        return device_id or None


def get_device_uuid(*, store_path: Path | None = None) -> str:
    """Return the stable device UUID from the local identity store."""
    return DeviceIdentity.load(store_path=store_path).device_uuid
