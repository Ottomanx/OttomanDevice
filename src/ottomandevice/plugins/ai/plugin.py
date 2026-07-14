from __future__ import annotations

from ottomandevice.config import settings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.plugins.ai.manager import AIManager
from ottomandevice.plugins.base import AIPlugin, PluginMetadata


class OttomanAIPlugin(AIPlugin):
    """Production AI runtime plugin for OttomanDevice."""

    PLUGIN_METADATA = PluginMetadata(
        id="ai",
        name="AI Runtime",
        version="1.0.0",
        author="OttomanX",
        description="Multi-provider AI orchestration with failover and streaming",
    )

    def __init__(self) -> None:
        self._manager: AIManager | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return self.PLUGIN_METADATA

    @property
    def manager(self) -> AIManager | None:
        return self._manager

    def install(self) -> None:
        return None

    def initialize(self) -> None:
        self._manager = AIManager.get_instance(event_bus=EventBus.get_instance())

    def start(self) -> None:
        if self._manager is None:
            raise RuntimeError("AI plugin is not initialized")
        if not settings.ai.enabled:
            return
        try:
            self._manager.start()
        except ConnectionError:
            return

    def stop(self) -> None:
        if self._manager is None:
            return
        self._manager.shutdown()

    def uninstall(self) -> None:
        if self._manager is not None:
            self._manager.shutdown()
            AIManager.reset_instance()
            self._manager = None
