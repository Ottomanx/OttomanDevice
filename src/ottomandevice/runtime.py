from __future__ import annotations

from ottomandevice.device import DeviceIdentity, get_device_uuid
from ottomandevice.paths import PROJECT_ROOT


def load_or_create_device_id() -> str:
    """Backward-compatible helper that returns the stable device UUID."""
    return get_device_uuid()


def get_device_id() -> str:
    """Backward-compatible helper that returns the stable device UUID."""
    return get_device_uuid()


def register_device(supabase, device=None) -> None:
    from ottomandevice.device.certificate import DeviceCertificate
    from ottomandevice.device.registry import DeviceRegistry

    identity = DeviceIdentity.load()
    certificate = DeviceCertificate.ensure(identity.device_uuid)
    DeviceRegistry(
        supabase=supabase,
        identity=identity,
        certificate=certificate,
    ).register()


class Device:
    """Backward-compatible device wrapper."""

    def __init__(self, device_id: str | None = None) -> None:
        self._identity = DeviceIdentity.load()

    @property
    def device_id(self) -> str:
        return self._identity.device_uuid


__all__ = [
    "PROJECT_ROOT",
    "Device",
    "DeviceIdentity",
    "get_device_id",
    "get_device_uuid",
    "load_or_create_device_id",
    "register_device",
]
