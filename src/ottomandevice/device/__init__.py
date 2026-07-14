"""OttomanDevice identity, registration, and profile management."""

from ottomandevice.device.certificate import DeviceCertificate
from ottomandevice.device.identity import DeviceIdentity, DeviceIdentityRecord, get_device_uuid
from ottomandevice.device.profile import DeviceProfile, PluginInfo
from ottomandevice.device.registry import DeviceRegistry, RegistrationResult

__all__ = [
    "DeviceCertificate",
    "DeviceIdentity",
    "DeviceIdentityRecord",
    "DeviceProfile",
    "DeviceRegistry",
    "PluginInfo",
    "RegistrationResult",
    "get_device_uuid",
]
