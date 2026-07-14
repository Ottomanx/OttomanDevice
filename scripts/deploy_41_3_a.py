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


if __name__ == "__main__":
    patch_event_bus()
    patch_exceptions()
    deploy_plugins()
    deploy_plugin_manager()
    patch_lifecycle()
    patch_core_init()
    write(
        "tests/unit/test_plugin_manager.py",
        (ROOT / "scripts" / "test_plugin_manager_src.py").read_text(encoding="utf-8"),
    )
