from __future__ import annotations

from ottomandevice.config import settings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.plugins.base import SpeechPlugin, PluginMetadata
from ottomandevice.plugins.speech.manager import SpeechManager


class OttomanSpeechPlugin(SpeechPlugin):
    """Production speech runtime plugin for OttomanDevice."""

    PLUGIN_METADATA = PluginMetadata(
        id="speech",
        name="Speech Runtime",
        version="1.0.0",
        author="OttomanX",
        description="Streaming STT/TTS pipeline with provider failover and AI integration",
    )

    def __init__(self) -> None:
        self._manager: SpeechManager | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return self.PLUGIN_METADATA

    @property
    def manager(self) -> SpeechManager | None:
        return self._manager

    def install(self) -> None:
        return None

    def initialize(self) -> None:
        self._manager = SpeechManager.get_instance(event_bus=EventBus.get_instance())

    def start(self) -> None:
        if self._manager is None:
            raise RuntimeError("Speech plugin is not initialized")
        if not settings.speech.enabled:
            return
        try:
            self._manager.start()
        except Exception:
            return

    def stop(self) -> None:
        if self._manager is None:
            return
        if self._manager.is_listening:
            self._manager.run_coroutine(self._manager.stop_listening())
        self._manager.shutdown()

    def uninstall(self) -> None:
        if self._manager is not None:
            self._manager.shutdown()
            SpeechManager.reset_instance()
            self._manager = None
