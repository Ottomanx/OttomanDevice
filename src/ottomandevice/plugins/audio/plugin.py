from __future__ import annotations

from ottomandevice.config import settings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.plugins.audio.manager import AudioManager
from ottomandevice.plugins.base import AudioPlugin, PluginMetadata


class OttomanAudioPlugin(AudioPlugin):
    """Production audio plugin for OttomanDevice."""

    PLUGIN_METADATA = PluginMetadata(
        id="audio",
        name="Audio Service",
        version="1.0.0",
        author="OttomanX",
        description="Auto-discovering microphone capture and PCM streaming service",
    )

    def __init__(self) -> None:
        self._manager: AudioManager | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return self.PLUGIN_METADATA

    @property
    def manager(self) -> AudioManager | None:
        return self._manager

    def install(self) -> None:
        return None

    def initialize(self) -> None:
        self._manager = AudioManager.get_instance(event_bus=EventBus.get_instance())

    def start(self) -> None:
        if self._manager is None:
            raise RuntimeError("Audio plugin is not initialized")

        if not settings.audio.enabled:
            return

        self._manager.register_health_monitor()
        self._manager.discover()

        opened = self._manager.open(settings.audio.device)
        self._manager.start_hotplug_monitor()
        if opened:
            self._manager.start_recording()

    def stop(self) -> None:
        if self._manager is None:
            return
        self._manager.stop_hotplug_monitor()
        self._manager.stop_recording()
        self._manager.close()

    def uninstall(self) -> None:
        if self._manager is not None:
            self._manager.shutdown()
            AudioManager.reset_instance()
            self._manager = None
