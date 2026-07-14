from __future__ import annotations

import time
from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ottomandevice.config.settings import RuntimeSessionSettings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.runtime.manager import ComponentBridge, SessionManager
from ottomandevice.runtime.pipeline import PipelineStage


@dataclass
class MockFrameResult:
    success: bool
    frame_number: int


class MockSpeechPipeline:
    async def ingest_audio(self, pcm: bytes) -> None:
        return None

    async def recognize_buffered(self) -> str:
        return "integration hello"

    async def speak(self, text: str) -> None:
        return None

    async def interrupt_playback(self) -> None:
        return None


class MockSpeechManager:
    def __init__(self) -> None:
        self.pipeline = MockSpeechPipeline()

    async def start_listening(self) -> None:
        return None

    async def stop_listening(self) -> None:
        return None


class MockAIManager:
    def create_session(self, session_id: str | None = None) -> SimpleNamespace:
        return SimpleNamespace(session_id=session_id or "integration-ai")

    async def complete(self, session_id: str, text: str) -> SimpleNamespace:
        return SimpleNamespace(text=f"integrated:{text}")


class MockCameraManager:
    def capture_frame(self) -> MockFrameResult:
        return MockFrameResult(success=True, frame_number=99)


class MockAudioManager:
    def read_chunk(self) -> SimpleNamespace:
        return SimpleNamespace(pcm=b"\x00\x01", success=True)


class MockAvatarManager:
    state = "speaking"


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=300)
    yield event_bus
    event_bus.shutdown()


@pytest.fixture(autouse=True)
def reset_singletons() -> None:
    SessionManager.reset_instance()
    yield
    SessionManager.reset_instance()


@pytest.fixture
def patched_settings() -> RuntimeSessionSettings:
    settings = RuntimeSessionSettings(
        enabled=True,
        idle_timeout=120,
        recovery_attempts=2,
        listen_timeout=30.0,
    )
    patcher = patch("ottomandevice.runtime.manager.settings")
    mock = patcher.start()
    mock.runtime_session = settings
    yield settings
    patcher.stop()


@pytest.fixture
def components() -> ComponentBridge:
    return ComponentBridge(
        camera=MockCameraManager(),
        audio=MockAudioManager(),
        speech=MockSpeechManager(),
        ai=MockAIManager(),
        avatar=MockAvatarManager(),
    )


def test_full_digital_human_interaction(
    bus: EventBus,
    patched_settings: RuntimeSessionSettings,
    components: ComponentBridge,
) -> None:
    events: list[str] = []
    for event_type in (
        "SessionStarted",
        "PipelineCompleted",
        "SessionEnded",
    ):
        bus.subscribe(event_type, lambda event, name=event_type: events.append(name))

    manager = SessionManager.get_instance(event_bus=bus, components=components)
    manager.start()
    session = manager.start_session()
    context = manager.run_interaction(pcm=b"integration-pcm", session_id=session.context.session_id)

    assert context.transcript == "integration hello"
    assert context.ai_response == "integrated:integration hello"
    assert context.camera_frame_number == 99
    assert context.pipeline_stage == PipelineStage.COMPLETED

    report = manager.health_report()
    assert report["active"] is True
    assert report["metrics"]["total_latency_ms"] >= 0.0

    manager.end_session(session.context.session_id)
    assert manager.active_session is None
    assert events[0] == "SessionStarted"
    assert "PipelineCompleted" in events
    assert events[-1] == "SessionEnded"


def test_integration_idle_timeout_end(
    bus: EventBus,
    components: ComponentBridge,
) -> None:
    fast_settings = RuntimeSessionSettings(
        enabled=True,
        idle_timeout=0,
        recovery_attempts=1,
        listen_timeout=5.0,
    )
    with patch("ottomandevice.runtime.manager.settings") as mock_settings:
        mock_settings.runtime_session = fast_settings
        manager = SessionManager.get_instance(event_bus=bus, components=components)
        manager.start()
        session = manager.start_session()
        manager.run_interaction(pcm=b"pcm")
        time.sleep(1.5)
        assert manager.active_session is None
