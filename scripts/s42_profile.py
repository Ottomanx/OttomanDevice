from __future__ import annotations

import platform
from dataclasses import asdict, dataclass
from typing import Any

import psutil

from ottomandevice.core.plugin_manager import PluginManager
from ottomandevice.device.identity import DeviceIdentity

RUNTIME_VERSION = "41.3"
APPLICATION_VERSION = "0.2.0"


@dataclass(frozen=True)
class PluginInfo:
    """Plugin metadata included in the device profile."""

    id: str
    name: str
    version: str
    state: str


@dataclass(frozen=True)
class DeviceProfile:
    """Runtime device capability and environment profile."""

    device_uuid: str
    hostname: str
    os: str
    architecture: str
    cpu: str
    ram_mb: int
    application_version: str
    runtime_version: str
    plugins: tuple[PluginInfo, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["plugins"] = [asdict(plugin) for plugin in self.plugins]
        return payload

    @classmethod
    def collect(
        cls,
        identity: DeviceIdentity,
        *,
        plugin_manager: PluginManager | None = None,
        application_version: str | None = None,
        runtime_version: str | None = None,
    ) -> DeviceProfile:
        """Collect a device profile from the current runtime environment."""
        memory = psutil.virtual_memory()
        cpu_name = platform.processor().strip() or platform.machine()
        plugins = cls._collect_plugins(plugin_manager)

        return cls(
            device_uuid=identity.device_uuid,
            hostname=identity.hostname,
            os=platform.platform(),
            architecture=platform.machine(),
            cpu=cpu_name,
            ram_mb=int(memory.total // (1024 * 1024)),
            application_version=application_version or APPLICATION_VERSION,
            runtime_version=runtime_version or RUNTIME_VERSION,
            plugins=plugins,
        )

    @staticmethod
    def _collect_plugins(plugin_manager: PluginManager | None) -> tuple[PluginInfo, ...]:
        if plugin_manager is None:
            return ()

        plugins: list[PluginInfo] = []
        for managed in plugin_manager.plugins.values():
            plugins.append(
                PluginInfo(
                    id=managed.metadata.id,
                    name=managed.metadata.name,
                    version=managed.metadata.version,
                    state=managed.state.value,
                )
            )
        return tuple(sorted(plugins, key=lambda item: item.id))
