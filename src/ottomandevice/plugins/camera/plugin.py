from __future__ import annotations

from ottomandevice.config import settings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.plugins.base import CameraPlugin, PluginMetadata
from ottomandevice.plugins.camera.manager import CameraManager


class OttomanCameraPlugin(CameraPlugin):
    """Production camera plugin for OttomanDevice."""

    PLUGIN_METADATA = PluginMetadata(
        id="camera",
        name="Camera Service",
        version="1.0.0",
        author="OttomanX",
        description="Auto-discovering camera capture and streaming service",
    )

    def __init__(self) -> None:
        self._manager: CameraManager | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return self.PLUGIN_METADATA

    @property
    def manager(self) -> CameraManager | None:
        return self._manager

    def install(self) -> None:
        return None

    def initialize(self) -> None:
        self._manager = CameraManager.get_instance(event_bus=EventBus.get_instance())

    def start(self) -> None:
        if self._manager is None:
            raise RuntimeError("Camera plugin is not initialized")

        if not settings.camera.enabled:
            return

        self._manager.register_health_monitor()
        self._manager.discover()

        opened = self._manager.open(settings.camera.device)
        if not opened:
            self._manager.start_hotplug_monitor()
            return

        self._manager.start_hotplug_monitor()

    def stop(self) -> None:
        if self._manager is None:
            return
        self._manager.stop_hotplug_monitor()
        self._manager.stop_stream()
        self._manager.close()

    def uninstall(self) -> None:
        if self._manager is not None:
            self._manager.shutdown()
            CameraManager.reset_instance()
            self._manager = None
