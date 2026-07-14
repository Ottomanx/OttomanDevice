from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print("wrote", target)


PLUGINS_INIT = """\"\"\"OttomanDevice runtime plugin packages.\"\"\"\n"""

PLUGINS_BASE = """from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class PluginMetadata:
    \"\"\"Immutable metadata describing a runtime plugin.\"\"\"

    id: str
    name: str
    version: str
    author: str
    dependencies: tuple[str, ...] = ()
    description: str = \"\"


class PluginState(str, Enum):
    \"\"\"Lifecycle states for managed plugins.\"\"\"

    DISCOVERED = \"discovered\"
    INSTALLED = \"installed\"
    INITIALIZED = \"initialized\"
    STARTED = \"started\"
    STOPPED = \"stopped\"
    UNINSTALLED = \"uninstalled\"
    FAILED = \"failed\"


class BasePlugin(ABC):
    \"\"\"Abstract base class for all OttomanDevice plugins.\"\"\"

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        \"\"\"Return plugin metadata.\"\"\"

    @abstractmethod
    def install(self) -> None:
        \"\"\"Prepare plugin resources on the host.\"\"\"

    @abstractmethod
    def initialize(self) -> None:
        \"\"\"Initialize plugin runtime state.\"\"\"

    @abstractmethod
    def start(self) -> None:
        \"\"\"Start plugin execution.\"\"\"

    @abstractmethod
    def stop(self) -> None:
        \"\"\"Stop plugin execution.\"\"\"

    @abstractmethod
    def uninstall(self) -> None:
        \"\"\"Remove plugin resources from the host.\"\"\"


class DevicePlugin(BasePlugin):
    \"\"\"Base class for device capability plugins.\"\"\"


class AIPlugin(BasePlugin):
    \"\"\"Base class for AI inference plugins.\"\"\"


class CameraPlugin(BasePlugin):
    \"\"\"Base class for camera pipeline plugins.\"\"\"


class AudioPlugin(BasePlugin):
    \"\"\"Base class for audio pipeline plugins.\"\"\"
"""


def deploy_plugins() -> None:
    write("src/ottomandevice/plugins/__init__.py", PLUGINS_INIT)
    write("src/ottomandevice/plugins/base.py", PLUGINS_BASE)


def deploy_plugin_manager() -> None:
    write(
        "src/ottomandevice/core/plugin_manager.py",
        (ROOT / "scripts" / "plugin_manager_src.py").read_text(encoding="utf-8"),
    )


def patch_event_bus() -> None:
    path = ROOT / "src/ottomandevice/core/event_bus.py"
    text = path.read_text(encoding="utf-8")
    if "class PluginInstalled" in text:
        print("event_bus already patched")
        return
    marker = "@dataclass(frozen=True)\nclass Subscription:"
    plugin_events = '''

@dataclass(frozen=True)
class PluginInstalled(Event):
    """Published when a plugin completes installation."""

    plugin_id: str = ""
    name: str = ""
    version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"plugin_id": self.plugin_id, "name": self.name, "version": self.version},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id, "name": self.name, "version": self.version}
        return data


@dataclass(frozen=True)
class PluginInitialized(Event):
    """Published when a plugin completes initialization."""

    plugin_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"plugin_id": self.plugin_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id}
        return data


@dataclass(frozen=True)
class PluginStarted(Event):
    """Published when a plugin starts successfully."""

    plugin_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"plugin_id": self.plugin_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id}
        return data


@dataclass(frozen=True)
class PluginStopped(Event):
    """Published when a plugin stops successfully."""

    plugin_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"plugin_id": self.plugin_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id}
        return data


@dataclass(frozen=True)
class PluginUninstalled(Event):
    """Published when a plugin is uninstalled."""

    plugin_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"plugin_id": self.plugin_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id}
        return data


@dataclass(frozen=True)
class PluginFailed(Event):
    """Published when a plugin lifecycle operation fails."""

    plugin_id: str = ""
    phase: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"plugin_id": self.plugin_id, "phase": self.phase, "error": self.error},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id, "phase": self.phase, "error": self.error}
        return data
'''
    if marker not in text:
        raise RuntimeError("event_bus patch marker not found")
    path.write_text(text.replace(marker, plugin_events + "\n\n" + marker), encoding="utf-8")
    print("patched", path)


def patch_exceptions() -> None:
    path = ROOT / "src/ottomandevice/core/exceptions.py"
    text = path.read_text(encoding="utf-8")
    if "class PluginError" in text:
        print("exceptions already patched")
        return
    needle = 'class HealthCheckError(OttomanDeviceError):\n    """Raised when a health probe fails."""\n\n\n'
    insert = needle + 'class PluginError(OttomanDeviceError):\n    """Raised when plugin discovery or lifecycle operations fail."""\n\n\n'
    if needle not in text:
        raise RuntimeError("exceptions patch marker not found")
    path.write_text(text.replace(needle, insert), encoding="utf-8")
    print("patched", path)


def patch_lifecycle() -> None:
    path = ROOT / "src/ottomandevice/core/lifecycle.py"
    text = path.read_text(encoding="utf-8")
    if "PluginManager" in text:
        print("lifecycle already patched")
        return
    text = text.replace(
        "from ottomandevice.core.performance import PerformanceMonitor\n",
        "from ottomandevice.core.performance import PerformanceMonitor\nfrom ottomandevice.core.plugin_manager import PluginManager\n",
    )
    text = text.replace(
        "        self._event_bus = EventBus.get_instance()\n",
        "        self._event_bus = EventBus.get_instance()\n        self._plugin_manager: PluginManager | None = None\n",
    )
    text = text.replace(
        "            self._register_services()\n            self._start_services()\n",
        "            self._register_services()\n            self._load_plugins()\n            self._start_services()\n",
    )
    text = text.replace(
        "    def _shutdown(self) -> None:\n        self._supervisor.stop_all()\n",
        "    def _shutdown(self) -> None:\n        if self._plugin_manager is not None:\n            self._plugin_manager.shutdown()\n        self._supervisor.stop_all()\n",
    )
    load_plugins = '''

    def _load_plugins(self) -> None:
        """Discover and start runtime plugins in dependency order."""
        self._plugin_manager = PluginManager.get_instance(event_bus=self._event_bus)
        self._plugin_manager.discover()
        self._plugin_manager.load_all()
        self._logger.info("Loaded %s plugin(s)", len(self._plugin_manager.plugins))

'''
    text = text.replace("    def _start_services(self) -> None:", load_plugins + "    def _start_services(self) -> None:")
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def patch_core_init() -> None:
    path = ROOT / "src/ottomandevice/core/__init__.py"
    text = path.read_text(encoding="utf-8")
    if "PluginManager" in text:
        print("core __init__ already patched")
        return
    text = text.replace(
        "    Subscription,\n)\n",
        "    Subscription,\n    PluginFailed,\n    PluginInitialized,\n    PluginInstalled,\n    PluginStarted,\n    PluginStopped,\n    PluginUninstalled,\n)\n",
    )
    text = text.replace("    ServiceError,\n)\n", "    ServiceError,\n    PluginError,\n)\n")
    text = text.replace(
        "from ottomandevice.core.lifecycle import Runtime\n",
        "from ottomandevice.core.lifecycle import Runtime\nfrom ottomandevice.core.plugin_manager import PluginManager\n",
    )
    text = text.replace(
        '    "Subscription",\n    "configure_logging",\n',
        '    "Subscription",\n    "PluginError",\n    "PluginManager",\n    "PluginFailed",\n    "PluginInitialized",\n    "PluginInstalled",\n    "PluginStarted",\n    "PluginStopped",\n    "PluginUninstalled",\n    "configure_logging",\n',
    )
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def deploy_device_modules() -> None:
    mapping = {
        "s42_identity.py": "src/ottomandevice/device/identity.py",
        "s42_certificate.py": "src/ottomandevice/device/certificate.py",
        "s42_profile.py": "src/ottomandevice/device/profile.py",
        "s42_registry.py": "src/ottomandevice/device/registry.py",
        "s42_init.py": "src/ottomandevice/device/__init__.py",
        "s42_tests.py": "tests/unit/test_device_identity.py",
    }
    for source, destination in mapping.items():
        write(destination, (ROOT / "scripts" / source).read_text(encoding="utf-8"))


def patch_event_bus_device_events() -> None:
    path = ROOT / "src/ottomandevice/core/event_bus.py"
    text = path.read_text(encoding="utf-8")
    if "class DeviceRegistered" in text:
        print("event_bus device events already patched")
        return
    marker = "@dataclass(frozen=True)\nclass Subscription:"
    device_events = '''

@dataclass(frozen=True)
class DeviceRegistered(Event):
    """Published when a device registers successfully with the cloud backend."""

    device_uuid: str = ""
    installation_id: str = ""
    is_new: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_uuid": self.device_uuid,
                "installation_id": self.installation_id,
                "is_new": self.is_new,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_uuid": self.device_uuid,
            "installation_id": self.installation_id,
            "is_new": self.is_new,
        }
        return data


@dataclass(frozen=True)
class DeviceRegistrationFailed(Event):
    """Published when cloud device registration fails."""

    device_uuid: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"device_uuid": self.device_uuid, "error": self.error},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "device_uuid": self.device_uuid, "error": self.error}
        return data


@dataclass(frozen=True)
class DeviceProfileUpdated(Event):
    """Published when the runtime device profile is synchronized to the cloud."""

    device_uuid: str = ""
    plugin_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"device_uuid": self.device_uuid, "plugin_count": self.plugin_count},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_uuid": self.device_uuid,
            "plugin_count": self.plugin_count,
        }
        return data
'''
    if marker not in text:
        raise RuntimeError("event_bus patch marker not found")
    path.write_text(text.replace(marker, device_events + "\n\n" + marker), encoding="utf-8")
    print("patched", path)


def patch_exceptions_device() -> None:
    path = ROOT / "src/ottomandevice/core/exceptions.py"
    text = path.read_text(encoding="utf-8")
    if "class DeviceIdentityError" in text:
        print("exceptions device already patched")
        return
    needle = 'class PluginError(OttomanDeviceError):\n    """Raised when plugin discovery or lifecycle operations fail."""\n\n\n'
    insert = needle + 'class DeviceIdentityError(OttomanDeviceError):\n    """Raised when device identity or registration operations fail."""\n\n\n'
    if needle not in text:
        raise RuntimeError("exceptions patch marker not found")
    path.write_text(text.replace(needle, insert), encoding="utf-8")
    print("patched", path)


def patch_startup_health() -> None:
    path = ROOT / "src/ottomandevice/startup/health.py"
    text = path.read_text(encoding="utf-8")
    if "DeviceRegistry" in text and "from ottomandevice.runtime import register_device" not in text:
        print("startup health already patched")
        return
    text = text.replace(
        "from ottomandevice.runtime import register_device\n",
        "from ottomandevice.device.certificate import DeviceCertificate\nfrom ottomandevice.device.identity import DeviceIdentity\nfrom ottomandevice.device.registry import DeviceRegistry\n",
    )
    old = '''def check_device_registration(supabase: Client) -> tuple[HealthStatus, str]:
    try:
        register_device(supabase)
        return "PASS", "Registered"
    except Exception as exc:
        return "FAIL", str(exc)
'''
    new = '''def check_device_registration(supabase: Client) -> tuple[HealthStatus, str]:
    try:
        identity = DeviceIdentity.load()
        certificate = DeviceCertificate.ensure(identity.device_uuid)
        if identity.certificate_fingerprint != certificate.fingerprint:
            identity = identity.with_certificate_fingerprint(certificate.fingerprint)
            identity.persist()
        registry = DeviceRegistry(
            supabase=supabase,
            identity=identity,
            certificate=certificate,
        )
        result = registry.register()
        if result.is_new:
            return "PASS", "Registered new device"
        return "PASS", "Reused existing device identity"
    except Exception as exc:
        return "FAIL", str(exc)
'''
    if old not in text:
        raise RuntimeError("startup health patch marker not found")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print("patched", path)


def patch_lifecycle_device() -> None:
    path = ROOT / "src/ottomandevice/core/lifecycle.py"
    text = path.read_text(encoding="utf-8")
    if "_sync_device_profile" in text:
        print("lifecycle device already patched")
        return
    text = text.replace(
        "from ottomandevice.core.plugin_manager import PluginManager\n",
        "from ottomandevice.core.plugin_manager import PluginManager\nfrom ottomandevice.device.certificate import DeviceCertificate\nfrom ottomandevice.device.identity import DeviceIdentity\nfrom ottomandevice.device.profile import DeviceProfile\nfrom ottomandevice.device.registry import DeviceRegistry\n",
    )
    text = text.replace(
        "        self._plugin_manager: PluginManager | None = None\n",
        "        self._plugin_manager: PluginManager | None = None\n        self._device_identity: DeviceIdentity | None = None\n        self._device_registry: DeviceRegistry | None = None\n",
    )
    text = text.replace(
        "            self._connect_supabase()\n            self._run_startup_checks()\n",
        "            self._connect_supabase()\n            self._initialize_device_identity()\n            self._run_startup_checks()\n",
    )
    init_method = '''

    def _initialize_device_identity(self) -> None:
        """Load local identity and ensure device certificate material exists."""
        self._device_identity = DeviceIdentity.load()
        certificate = DeviceCertificate.ensure(self._device_identity.device_uuid)
        if self._device_identity.certificate_fingerprint != certificate.fingerprint:
            self._device_identity = self._device_identity.with_certificate_fingerprint(
                certificate.fingerprint
            )
            self._device_identity.persist()
        assert self._supabase is not None
        self._device_registry = DeviceRegistry(
            supabase=self._supabase,
            identity=self._device_identity,
            certificate=certificate,
            event_bus=self._event_bus,
        )
        self._logger.info("Device identity loaded: %s", self._device_identity.device_uuid)

'''
    text = text.replace("    def _run_startup_checks(self) -> None:", init_method + "    def _run_startup_checks(self) -> None:")
    sync_method = '''

    def _sync_device_profile(self) -> None:
        """Publish the runtime device profile after plugins are loaded."""
        if self._device_identity is None or self._device_registry is None:
            return
        profile = DeviceProfile.collect(
            self._device_identity,
            plugin_manager=self._plugin_manager,
        )
        self._device_registry.update_profile(profile)
        self._logger.info(
            "Device profile synchronized (%s plugins)",
            len(profile.plugins),
        )

'''
    text = text.replace(
        "        self._logger.info(\"Loaded %s plugin(s)\", len(self._plugin_manager.plugins))\n",
        "        self._logger.info(\"Loaded %s plugin(s)\", len(self._plugin_manager.plugins))\n        self._sync_device_profile()\n",
    )
    text = text.replace("    def _start_services(self) -> None:", sync_method + "    def _start_services(self) -> None:")
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def patch_runtime() -> None:
    path = ROOT / "src/ottomandevice/runtime.py"
    text = '''from __future__ import annotations

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
'''
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def patch_device_root() -> None:
    path = ROOT / "device.py"
    text = '''"""Backward-compatible device registration shims."""

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
'''
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def patch_core_init_device() -> None:
    path = ROOT / "src/ottomandevice/core/__init__.py"
    text = path.read_text(encoding="utf-8")
    if "DeviceRegistered" in text:
        print("core init device already patched")
        return
    text = text.replace(
        "    PluginUninstalled,\n)\n",
        "    PluginUninstalled,\n    DeviceRegistered,\n    DeviceRegistrationFailed,\n    DeviceProfileUpdated,\n)\n",
    )
    text = text.replace(
        "    PluginError,\n)\n",
        "    PluginError,\n    DeviceIdentityError,\n)\n",
    )
    text = text.replace(
        '    "PluginUninstalled",\n    "configure_logging",\n',
        '    "PluginUninstalled",\n    "DeviceRegistered",\n    "DeviceRegistrationFailed",\n    "DeviceProfileUpdated",\n    "DeviceIdentityError",\n    "configure_logging",\n',
    )
    path.write_text(text, encoding="utf-8")
    print("patched", path)


def write_migration() -> None:
    migration = '''/*
  # Sprint 42 device identity profile columns
*/

ALTER TABLE devices_enhanced
  ADD COLUMN IF NOT EXISTS installation_id text,
  ADD COLUMN IF NOT EXISTS architecture text,
  ADD COLUMN IF NOT EXISTS cpu_model text,
  ADD COLUMN IF NOT EXISTS ram_total_mb integer,
  ADD COLUMN IF NOT EXISTS application_version text,
  ADD COLUMN IF NOT EXISTS runtime_version text,
  ADD COLUMN IF NOT EXISTS certificate_fingerprint text,
  ADD COLUMN IF NOT EXISTS device_profile jsonb,
  ADD COLUMN IF NOT EXISTS first_boot_timestamp timestamptz,
  ADD COLUMN IF NOT EXISTS registration_signature text;
'''
    write("supabase/migrations/20260714120000_add_device_identity_profile.sql", migration)


if __name__ == "__main__":
    patch_event_bus_device_events()
    patch_exceptions_device()
    deploy_device_modules()
    patch_startup_health()
    patch_lifecycle_device()
    patch_runtime()
    patch_device_root()
    patch_core_init_device()
    write_migration()
