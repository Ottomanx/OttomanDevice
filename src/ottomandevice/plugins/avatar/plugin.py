from __future__ import annotations

from ottomandevice.config import settings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.plugins.avatar.manager import AvatarManager
from ottomandevice.plugins.base import AvatarPlugin, PluginMetadata


class OttomanAvatarPlugin(AvatarPlugin):
    """Production avatar runtime plugin for OttomanDevice."""

    PLUGIN_METADATA = PluginMetadata(
        id="avatar",
        name="Avatar Runtime",
        version="1.0.0",
        author="OttomanX",
        description="Digital human rendering with lip sync, emotions, and animation queue",
    )

    def __init__(self) -> None:
        self._manager: AvatarManager | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return self.PLUGIN_METADATA

    @property
    def manager(self) -> AvatarManager | None:
        return self._manager

    def install(self) -> None:
        return None

    def initialize(self) -> None:
        self._manager = AvatarManager.get_instance(event_bus=EventBus.get_instance())

    def start(self) -> None:
        if self._manager is None:
            raise RuntimeError("Avatar plugin is not initialized")
        if not settings.avatar.enabled:
            return
        try:
            self._manager.start()
        except Exception:
            return

    def stop(self) -> None:
        if self._manager is None:
            return
        self._manager.shutdown()

    def uninstall(self) -> None:
        if self._manager is not None:
            self._manager.shutdown()
            AvatarManager.reset_instance()
            self._manager = None
