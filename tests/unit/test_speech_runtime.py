from __future__ import annotations

import asyncio
import struct
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ottomandevice.config.settings import SpeechSettings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.core.plugin_manager import PluginManager
from ottomandevice.plugins.ai.provider import AIResponse
from ottomandevice.plugins.speech.buffer import AudioBuffer
from ottomandevice.plugins.speech.manager import SpeechManager
from ottomandevice.plugins.speech.pipeline import SpeechPipeline
from ottomandevice.plugins.speech.plugin import OttomanSpeechPlugin
from ottomandevice.plugins.speech.provider import (
    STTProvider,
    SynthesisChunk,
    SynthesisResult,
    TranscriptChunk,
    TranscriptionResult,
    TTSProvider,
)
from ottomandevice.plugins.speech.vad import VoiceActivityDetector
from ottomandevice.plugins.speech.wake_word import WakeWordFramework


class MockSTTProvider(STTProvider):
    def __init__(
        self,
        name: str,
        *,
        connect_error: Exception | None = None,
        transcribe_error: Exception | None = None,
        text: str = "hello world",
    ) -> None:
        self._name = name
        self._connect_error = connect_error
        self._transcribe_error = transcribe_error
        self._text = text
        self._connected = False

    @property
    def name(self) -> str:
        return self._name

    async def connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def is_available(self) -> bool:
        return self._connected

    async def transcribe(self, pcm: bytes, *, language: str = "auto") -> TranscriptionResult:
        if self._transcribe_error is not None:
            raise self._transcribe_error
        return TranscriptionResult(
            text=self._text,
            language=language,
            confidence=0.95,
            latency_ms=25.0,
            provider=self._name,
        )

    async def transcribe_stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        language: str = "auto",
    ) -> AsyncIterator[TranscriptChunk]:
        async for _chunk in audio_chunks:
            yield TranscriptChunk(text="partial", is_final=False, language=language)
        yield TranscriptChunk(text=self._text, is_final=True, language=language)


class MockTTSProvider(TTSProvider):
    def __init__(
        self,
        name: str,
        *,
        connect_error: Exception | None = None,
        synthesize_error: Exception | None = None,
        audio: bytes = b"\x00\x01\x02\x03",
    ) -> None:
        self._name = name
        self._connect_error = connect_error
        self._synthesize_error = synthesize_error
        self._audio = audio
        self._connected = False

    @property
    def name(self) -> str:
        return self._name

    async def connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def is_available(self) -> bool:
        return self._connected

    async def synthesize(self, text: str, *, language: str = "auto") -> SynthesisResult:
        if self._synthesize_error is not None:
            raise self._synthesize_error
        return SynthesisResult(audio=self._audio, latency_ms=18.0, provider=self._name)

    async def synthesize_stream(
        self,
        text: str,
        *,
        language: str = "auto",
    ) -> AsyncIterator[SynthesisChunk]:
        if self._synthesize_error is not None:
            raise self._synthesize_error
        yield SynthesisChunk(audio=self._audio[:2], done=False)
        yield SynthesisChunk(audio=self._audio[2:], done=True)


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=200)
    yield event_bus
    event_bus.shutdown()


@pytest.fixture(autouse=True)
def reset_singletons() -> None:
    SpeechManager.reset_instance()
    PluginManager.reset_instance()
    yield
    SpeechManager.reset_instance()
    PluginManager.reset_instance()


@pytest.fixture
def speech_settings() -> SpeechSettings:
    return SpeechSettings(
        enabled=True,
        stt_provider="whisper",
        tts_provider="elevenlabs",
        stt_fallback=("azure",),
        tts_fallback=("azure",),
        streaming=True,
        language="auto",
    )


@pytest.fixture
def patched_settings(speech_settings: SpeechSettings):
    patches = [
        patch("ottomandevice.plugins.speech.manager.settings"),
        patch("ottomandevice.plugins.speech.plugin.settings"),
    ]
    mocks = [item.start() for item in patches]
    for mock in mocks:
        mock.speech = speech_settings
    yield speech_settings
    for item in patches:
        item.stop()


@pytest.fixture
def stt_providers() -> dict[str, MockSTTProvider]:
    return {
        "whisper": MockSTTProvider("whisper"),
        "azure": MockSTTProvider("azure", text="azure transcript"),
    }


@pytest.fixture
def tts_providers() -> dict[str, MockTTSProvider]:
    return {
        "elevenlabs": MockTTSProvider("elevenlabs"),
        "azure": MockTTSProvider("azure", audio=b"azure-audio"),
    }


def _manager(
    bus: EventBus,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> SpeechManager:
    return SpeechManager.get_instance(
        event_bus=bus,
        stt_providers=stt_providers,
        tts_providers=tts_providers,
    )


def _loud_pcm() -> bytes:
    samples = [20000] * 256
    return struct.pack(f"<{len(samples)}h", *samples)


def test_audio_buffer_append_and_drain() -> None:
    buffer = AudioBuffer(max_bytes=10)
    buffer.append(b"abc")
    buffer.append(b"def")
    assert buffer.size == 6
    assert buffer.drain() == b"abcdef"
    assert buffer.size == 0


def test_audio_buffer_evicts_oldest() -> None:
    buffer = AudioBuffer(max_bytes=5)
    buffer.append(b"abc")
    buffer.append(b"def")
    assert buffer.size == 3
    assert buffer.drain() == b"def"


def test_vad_detects_speech() -> None:
    vad = VoiceActivityDetector(threshold_db=-50.0)
    assert vad.process(_loud_pcm()) is True
    assert vad.is_speech_active is True


def test_wake_word_framework_invokes_callback() -> None:
    framework = WakeWordFramework()
    framework.enable()
    triggered: list[str] = []
    framework.register("hey ottoman", lambda phrase: triggered.append(phrase))
    assert framework.process_transcript("Hey Ottoman, turn on lights") is True
    assert triggered == ["hey ottoman"]


@pytest.mark.asyncio
async def test_stt_provider_abstraction(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    result = await manager.transcribe_pcm(b"pcm")
    assert result.text == "hello world"
    assert result.provider == "whisper"
    manager.shutdown()


@pytest.mark.asyncio
async def test_tts_provider_abstraction(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    result = await manager.synthesize_text("hello")
    assert result.audio == b"\x00\x01\x02\x03"
    assert result.provider == "elevenlabs"
    manager.shutdown()


@pytest.mark.asyncio
async def test_stt_failover(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    stt_providers["whisper"] = MockSTTProvider("whisper", transcribe_error=RuntimeError("whisper down"))
    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    result = await manager.transcribe_pcm(b"pcm")
    assert result.provider == "azure"
    assert result.text == "azure transcript"
    manager.shutdown()


@pytest.mark.asyncio
async def test_tts_failover(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    tts_providers["elevenlabs"] = MockTTSProvider("elevenlabs", synthesize_error=RuntimeError("eleven down"))
    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    result = await manager.synthesize_text("hello")
    assert result.provider == "azure"
    assert result.audio == b"azure-audio"
    manager.shutdown()


@pytest.mark.asyncio
async def test_streaming_stt_pipeline(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    await manager.pipeline.ingest_audio(b"chunk")
    chunks: list[str] = []
    async for chunk in manager.pipeline.recognize_stream():
        chunks.append(chunk.text)
    assert chunks == ["partial", "hello world"]
    manager.shutdown()


@pytest.mark.asyncio
async def test_streaming_playback_buffers_audio(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    await manager.play_text("hello")
    assert manager._playback_buffer.size == 4
    manager.shutdown()


def test_listening_events(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    events: list[str] = []
    bus.subscribe("SpeechListeningStarted", lambda event: events.append(event.event_type))
    bus.subscribe("SpeechListeningStopped", lambda event: events.append(event.event_type))

    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    manager.run_coroutine(manager.start_listening())
    manager.run_coroutine(manager.stop_listening())
    assert events == ["SpeechListeningStarted", "SpeechListeningStopped"]
    manager.shutdown()


def test_recognition_events(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    events: list[str] = []
    bus.subscribe("SpeechRecognized", lambda event: events.append(event.event_type))

    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    manager.run_coroutine(manager.transcribe_pcm(b"pcm"))
    assert events == ["SpeechRecognized"]
    manager.shutdown()


def test_recognition_failed_event(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    for provider in stt_providers.values():
        provider._transcribe_error = RuntimeError("failed")
    events: list[str] = []
    bus.subscribe("SpeechRecognitionFailed", lambda event: events.append(event.event_type))

    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    with pytest.raises(RuntimeError):
        manager.run_coroutine(manager.transcribe_pcm(b"pcm"))
    assert events == ["SpeechRecognitionFailed"]
    manager.shutdown()


def test_playback_events(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    events: list[str] = []
    bus.subscribe("SpeechPlaybackStarted", lambda event: events.append(event.event_type))
    bus.subscribe("SpeechPlaybackCompleted", lambda event: events.append(event.event_type))

    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    manager.run_coroutine(manager.play_text("hello"))
    assert events == ["SpeechPlaybackStarted", "SpeechPlaybackCompleted"]
    manager.shutdown()


@pytest.mark.asyncio
async def test_interruptible_playback(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    events: list[str] = []
    bus.subscribe("SpeechPlaybackInterrupted", lambda event: events.append(event.event_type))

    slow_tts = MockTTSProvider("elevenlabs")

    async def slow_stream(text: str, *, language: str = "auto") -> AsyncIterator[SynthesisChunk]:
        yield SynthesisChunk(audio=b"aa", done=False)
        await asyncio.sleep(0.05)
        yield SynthesisChunk(audio=b"bb", done=True)

    slow_tts.synthesize_stream = slow_stream  # type: ignore[method-assign]
    tts_providers["elevenlabs"] = slow_tts

    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    interrupt = asyncio.Event()

    async def run_playback() -> None:
        await manager.play_text("hello", interrupt_event=interrupt)

    playback_task = asyncio.create_task(run_playback())
    await asyncio.sleep(0.01)
    interrupt.set()
    await playback_task
    assert events == ["SpeechPlaybackInterrupted"]
    manager.shutdown()


@pytest.mark.asyncio
async def test_pipeline_converse_with_ai(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    await manager.pipeline.ingest_audio(b"pcm")

    ai_manager = MagicMock()
    ai_response = AIResponse(
        text="ai reply",
        provider="openai",
        model="gpt",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        latency_ms=10.0,
    )

    async def complete(session_id: str, text: str) -> AIResponse:
        assert session_id == "session-1"
        assert text == "hello world"
        return ai_response

    ai_manager.complete = complete

    with patch(
        "ottomandevice.plugins.ai.manager.AIManager.get_instance_optional",
        return_value=ai_manager,
    ):
        response = await manager.pipeline.converse_with_ai("session-1")
    assert response.text == "ai reply"
    manager.shutdown()


def test_plugin_metadata() -> None:
    plugin = OttomanSpeechPlugin()
    assert plugin.metadata.id == "speech"


def test_plugin_starts_without_credentials(bus: EventBus, patched_settings) -> None:
    failing_stt = {
        "whisper": MockSTTProvider("whisper", connect_error=ConnectionError("no key")),
        "azure": MockSTTProvider("azure", connect_error=ConnectionError("no key")),
    }
    failing_tts = {
        "elevenlabs": MockTTSProvider("elevenlabs", connect_error=ConnectionError("no key")),
        "azure": MockTTSProvider("azure", connect_error=ConnectionError("no key")),
    }
    plugin = OttomanSpeechPlugin()
    plugin.install()
    with patch.object(
        SpeechManager,
        "get_instance",
        return_value=SpeechManager(event_bus=bus, stt_providers=failing_stt, tts_providers=failing_tts),
    ):
        plugin.initialize()
        plugin.start()
    plugin.stop()
    plugin.uninstall()


def test_speech_plugin_discovered(bus: EventBus) -> None:
    import importlib
    from pathlib import Path

    package = importlib.import_module("ottomandevice.plugins")
    plugins_root = Path(package.__path__[0])
    manager = PluginManager(plugins_root=plugins_root, event_bus=bus)
    discovered = manager.discover()
    assert "speech" in discovered


def test_health_report_tracks_latency(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    manager.run_coroutine(manager.transcribe_pcm(b"pcm"))
    manager.run_coroutine(manager.play_text("hello"))
    report = manager.health_report()
    assert report["active_stt"] == "whisper"
    assert report["active_tts"] == "elevenlabs"
    assert report["metrics"]["stt_requests"] == 1
    assert report["metrics"]["tts_requests"] == 1
    manager.shutdown()


def test_cloud_speech_health_snapshot(
    bus: EventBus,
    patched_settings,
    stt_providers: dict[str, MockSTTProvider],
    tts_providers: dict[str, MockTTSProvider],
) -> None:
    from ottomandevice.cloud.device_manager import _speech_health_snapshot

    manager = _manager(bus, stt_providers, tts_providers)
    manager.start()
    snapshot = _speech_health_snapshot()
    assert snapshot is not None
    assert snapshot["active_stt"] == "whisper"
    manager.shutdown()
