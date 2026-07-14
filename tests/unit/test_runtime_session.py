from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from ottomandevice.config.settings import RuntimeSessionSettings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.runtime.context import SessionContext
from ottomandevice.runtime.manager import ComponentBridge, SessionManager
from ottomandevice.runtime.metrics import SessionMetrics
from ottomandevice.runtime.pipeline import InteractionPipeline, PipelineStage
from ottomandevice.runtime.session import RuntimeSession, SessionLifecycle


@dataclass
class MockFrameResult:
    success: bool
    frame_number: int


class MockSpeechPipeline:
    def __init__(self, *, transcript: str = "hello device", fail_once: bool = False) -> None:
        self._transcript = transcript
        self._fail_once = fail_once
        self._spoken: list[str] = []
        self._ingested: list[bytes] = []

    async def ingest_audio(self, pcm: bytes) -> None:
        self._ingested.append(pcm)

    async def recognize_buffered(self) -> str:
        if self._fail_once:
            self._fail_once = False
            return ""
        return self._transcript

    async def speak(self, text: str) -> None:
        self._spoken.append(text)

    async def interrupt_playback(self) -> None:
        return None


class MockSpeechManager:
    def __init__(self, *, transcript: str = "hello device", fail_once: bool = False) -> None:
        self.pipeline = MockSpeechPipeline(transcript=transcript, fail_once=fail_once)
        self.listening = False

    async def start_listening(self) -> None:
        self.listening = True

    async def stop_listening(self) -> None:
        self.listening = False


class MockAIManager:
    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}

    def create_session(self, session_id: str | None = None) -> SimpleNamespace:
        resolved = session_id or "ai-session"
        self._sessions[resolved] = resolved
        return SimpleNamespace(session_id=resolved)

    async def complete(self, session_id: str, text: str) -> SimpleNamespace:
        return SimpleNamespace(text=f"reply:{text}")


class MockCameraManager:
    def capture_frame(self) -> MockFrameResult:
        return MockFrameResult(success=True, frame_number=7)


class MockAvatarManager:
    state = "idle"


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=200)
    yield event_bus
    event_bus.shutdown()


@pytest.fixture(autouse=True)
def reset_singletons() -> None:
    SessionManager.reset_instance()
    yield
    SessionManager.reset_instance()


@pytest.fixture
def session_settings() -> RuntimeSessionSettings:
    return RuntimeSessionSettings(
        enabled=True,
        idle_timeout=120,
        recovery_attempts=2,
        listen_timeout=30.0,
    )


@pytest.fixture
def patched_settings(session_settings: RuntimeSessionSettings):
    patcher = patch("ottomandevice.runtime.manager.settings")
    mock = patcher.start()
    mock.runtime_session = session_settings
    yield session_settings
    patcher.stop()


@pytest.fixture
def components() -> ComponentBridge:
    return ComponentBridge(
        camera=MockCameraManager(),
        speech=MockSpeechManager(),
        ai=MockAIManager(),
        avatar=MockAvatarManager(),
    )


def _manager(bus: EventBus, components: ComponentBridge) -> SessionManager:
    manager = SessionManager.get_instance(event_bus=bus, components=components)
    manager.start()
    return manager


def test_session_context_tracks_activity() -> None:
    context = SessionContext()
    context.set_stage("stt")
    assert context.pipeline_stage == "stt"
    snapshot = context.snapshot()
    assert snapshot["session_id"] == context.session_id


def test_session_metrics_record_interaction() -> None:
    metrics = SessionMetrics()
    metrics.record_interaction(stt_ms=10.0, ai_ms=20.0, tts_ms=30.0, avatar_ms=1.0)
    data = metrics.to_dict()
    assert data["total_latency_ms"] == 61.0
    assert data["interactions_completed"] == 1


@pytest.mark.asyncio
async def test_interaction_pipeline_end_to_end(components: ComponentBridge) -> None:
    context = SessionContext()
    metrics = SessionMetrics()
    pipeline = InteractionPipeline(components, context=context, metrics=metrics)
    result = await pipeline.run(pcm=b"pcm-data")
    assert result.transcript == "hello device"
    assert result.ai_response == "reply:hello device"
    assert result.camera_frame_number == 7
    assert result.pipeline_stage == PipelineStage.COMPLETED
    assert metrics.interactions_completed == 1


def test_session_started_event(
    bus: EventBus,
    patched_settings,
    components: ComponentBridge,
) -> None:
    events: list[str] = []
    bus.subscribe("SessionStarted", lambda event: events.append(event.event_type))
    manager = _manager(bus, components)
    session = manager.start_session()
    assert session.lifecycle == SessionLifecycle.ACTIVE
    assert "SessionStarted" in events
    manager.end_session(session.context.session_id)


def test_pipeline_completed_event(
    bus: EventBus,
    patched_settings,
    components: ComponentBridge,
) -> None:
    events: list[str] = []
    bus.subscribe("PipelineCompleted", lambda event: events.append(event.event_type))
    manager = _manager(bus, components)
    context = manager.run_interaction(pcm=b"audio")
    assert context.ai_response.startswith("reply:")
    assert events == ["PipelineCompleted"]
    manager.end_session()


def test_concurrent_session_protection(
    bus: EventBus,
    patched_settings,
    components: ComponentBridge,
) -> None:
    manager = _manager(bus, components)
    manager.start_session()
    with pytest.raises(RuntimeError, match="Concurrent"):
        manager.start_session()
    manager.end_session()


def test_session_recovery(
    bus: EventBus,
    patched_settings,
    components: ComponentBridge,
) -> None:
    speech = MockSpeechManager(fail_once=True)
    bridge = ComponentBridge(
        camera=MockCameraManager(),
        speech=speech,
        ai=MockAIManager(),
        avatar=MockAvatarManager(),
    )
    events: list[str] = []
    bus.subscribe("SessionRecovered", lambda event: events.append(event.event_type))
    manager = _manager(bus, bridge)
    context = manager.run_interaction(pcm=b"audio")
    assert context.transcript == "hello device"
    assert "SessionRecovered" in events
    manager.end_session()


def test_session_failed_after_recovery_exhausted(
    bus: EventBus,
    patched_settings,
) -> None:
    class AlwaysFailSpeech(MockSpeechManager):
        async def start_listening(self) -> None:
            return None

    class FailPipeline(MockSpeechPipeline):
        async def recognize_buffered(self) -> str:
            return ""

    speech = AlwaysFailSpeech()
    speech.pipeline = FailPipeline()
    bridge = ComponentBridge(
        camera=MockCameraManager(),
        speech=speech,
        ai=MockAIManager(),
        avatar=MockAvatarManager(),
    )
    events: list[str] = []
    bus.subscribe("SessionFailed", lambda event: events.append(event.event_type))
    manager = _manager(bus, bridge)
    with pytest.raises(RuntimeError):
        manager.run_interaction(pcm=b"audio")
    assert events == ["SessionFailed"]
    manager.end_session()


@pytest.mark.asyncio
async def test_pipeline_graceful_cancellation(components: ComponentBridge) -> None:
    context = SessionContext()
    metrics = SessionMetrics()
    pipeline = InteractionPipeline(components, context=context, metrics=metrics)

    original_ingest = components.speech.pipeline.ingest_audio

    async def ingest_and_cancel(pcm: bytes) -> None:
        await original_ingest(pcm)
        pipeline.cancel_event.set()

    components.speech.pipeline.ingest_audio = ingest_and_cancel  # type: ignore[method-assign]
    with pytest.raises(asyncio.CancelledError):
        await pipeline.run(pcm=b"audio")


def test_health_report_active_pipeline(
    bus: EventBus,
    patched_settings,
    components: ComponentBridge,
) -> None:
    manager = _manager(bus, components)
    manager.run_interaction(pcm=b"audio")
    report = manager.health_report()
    assert report["active"] is True
    assert report["metrics"]["interactions_completed"] == 1
    assert report["pipeline_stage"] == PipelineStage.COMPLETED
    manager.end_session()


def test_session_ended_event(
    bus: EventBus,
    patched_settings,
    components: ComponentBridge,
) -> None:
    events: list[str] = []
    bus.subscribe("SessionEnded", lambda event: events.append(event.event_type))
    manager = _manager(bus, components)
    session = manager.start_session()
    manager.end_session(session.context.session_id)
    assert "SessionEnded" in events
    assert manager.active_session is None


def test_cloud_session_health_snapshot(
    bus: EventBus,
    patched_settings,
    components: ComponentBridge,
) -> None:
    from ottomandevice.cloud.device_manager import _session_health_snapshot

    manager = _manager(bus, components)
    manager.run_interaction(pcm=b"audio")
    snapshot = _session_health_snapshot()
    assert snapshot is not None
    assert snapshot["metrics"]["interactions_completed"] == 1
    manager.end_session()
