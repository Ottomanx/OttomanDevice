from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ottomandevice.core.exceptions import DeviceIdentityError
from ottomandevice.paths import PROJECT_ROOT

CERTIFICATE_DIR = PROJECT_ROOT / "data" / "device"
PRIVATE_KEY_PATH = CERTIFICATE_DIR / "private.key"
PUBLIC_KEY_PATH = CERTIFICATE_DIR / "public.key"
METADATA_PATH = CERTIFICATE_DIR / "certificate.json"
_KEY_SIZE_BYTES = 32
_CERT_LOCK = threading.RLock()


@dataclass(frozen=True)
class DeviceCertificateMetadata:
    """Persisted certificate metadata for a device."""

    device_uuid: str
    fingerprint: str
    algorithm: str
    issued_at: str
    public_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeviceCertificate:
    """Device attestation certificate and signing material."""

    def __init__(self, *, device_uuid: str, private_key: bytes, metadata: DeviceCertificateMetadata) -> None:
        self._device_uuid = device_uuid
        self._private_key = private_key
        self._metadata = metadata

    @property
    def device_uuid(self) -> str:
        return self._device_uuid

    @property
    def fingerprint(self) -> str:
        return self._metadata.fingerprint

    @property
    def algorithm(self) -> str:
        return self._metadata.algorithm

    @property
    def issued_at(self) -> datetime:
        return datetime.fromisoformat(self._metadata.issued_at)

    @property
    def public_key(self) -> str:
        return self._metadata.public_key

    @classmethod
    def ensure(cls, device_uuid: str) -> DeviceCertificate:
        """Load an existing certificate or create one for the device."""
        with _CERT_LOCK:
            if METADATA_PATH.exists() and PRIVATE_KEY_PATH.exists():
                return cls._load_existing(device_uuid)
            return cls._create_new(device_uuid)

    def sign(self, payload: bytes) -> str:
        """Return a hex-encoded HMAC signature for registration payloads."""
        digest = hmac.new(self._private_key, payload, hashlib.sha256).hexdigest()
        return digest

    def registration_signature(self, *, installation_id: str, timestamp: str) -> str:
        """Sign the canonical registration payload for cloud enrollment."""
        canonical = f"{self._device_uuid}:{installation_id}:{timestamp}".encode("utf-8")
        return self.sign(canonical)

    @classmethod
    def _load_existing(cls, expected_device_uuid: str) -> DeviceCertificate:
        try:
            metadata_payload = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
            private_key = base64.b64decode(PRIVATE_KEY_PATH.read_text(encoding="utf-8").strip())
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise DeviceIdentityError("Unable to load device certificate material") from exc

        metadata = DeviceCertificateMetadata(
            device_uuid=str(metadata_payload["device_uuid"]),
            fingerprint=str(metadata_payload["fingerprint"]),
            algorithm=str(metadata_payload["algorithm"]),
            issued_at=str(metadata_payload["issued_at"]),
            public_key=str(metadata_payload["public_key"]),
        )

        if metadata.device_uuid != expected_device_uuid:
            raise DeviceIdentityError(
                "Certificate device UUID does not match local identity"
            )

        return cls(device_uuid=metadata.device_uuid, private_key=private_key, metadata=metadata)

    @classmethod
    def _create_new(cls, device_uuid: str) -> DeviceCertificate:
        private_key = secrets.token_bytes(_KEY_SIZE_BYTES)
        public_key = hashlib.sha256(private_key).digest()
        fingerprint = hashlib.sha256(public_key).hexdigest()
        issued_at = datetime.now(timezone.utc).isoformat()
        metadata = DeviceCertificateMetadata(
            device_uuid=device_uuid,
            fingerprint=fingerprint,
            algorithm="HMAC-SHA256",
            issued_at=issued_at,
            public_key=base64.b64encode(public_key).decode("ascii"),
        )

        CERTIFICATE_DIR.mkdir(parents=True, exist_ok=True)
        PRIVATE_KEY_PATH.write_text(base64.b64encode(private_key).decode("ascii") + "\n", encoding="utf-8")
        PUBLIC_KEY_PATH.write_text(metadata.public_key + "\n", encoding="utf-8")
        METADATA_PATH.write_text(json.dumps(metadata.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

        return cls(device_uuid=device_uuid, private_key=private_key, metadata=metadata)
