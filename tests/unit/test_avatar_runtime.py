from __future__ import annotations

import asyncio
import struct
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ottomandevice.config.settings import AvatarSettings
from ottomandevice.core.event_bus import (
    AIRequestStarted,
    AvatarAnimationCompleted,
    AvatarAnimationStarted,
    AvatarLoaded,
    AvatarStateChanged,
    EventBus,
    SpeechListeningStarted,
    SpeechPlaybackCompleted,
    SpeechPlaybackStarted,
)
from ottomandevice.core.plugin_manager import PluginManager
from ottomandevice.plugins.avatar.animation import AnimationController, AnimationRequest
from ottomandevice.plugins.avatar.emotion import Emotion, EmotionEngine
from ottomandevice.plugins.avatar.lipsync import LipSyncEngine
from ottomandevice.plugins.avatar.manager import AvatarManager
from ottomandevice.plugins.avatar.plugin import OttomanAvatarPlugin
from ottomandevice.plugins.avatar.renderer import AvatarRenderFrame, AvatarRenderer
from ottomandevice.plugins.avatar.state import AvatarState, AvatarStateMachine
from ottomandevice.plugins.speech.buffer import AudioBuffer


class MockAvatarRenderer(AvatarRenderer):
    def __init__(self) -> None:
        self.initialized = False
        self.loaded = False
        self.frames: list[AvatarRenderFrame] = []

    @property
    def backend(self) -> str:
        return "mock"

    async def initialize(self, *, target_fps: int = 60) -> None:
        self.initialized = True

    async def load_avatar(self, asset_id: str = "default") -> None:
        self.loaded = True

    async def render(self, frame: AvatarRenderFrame) -> None:
        self.frames.append(frame)

    async def shutdown(self) -> None:
        self.initialized = False
        self.loaded = False


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=200)
    yield event_bus
    event_bus.shutdown()


@pytest.fixture(autouse=True)
def reset_singletons() -> None:
    AvatarManager.reset_instance()
    PluginManager.reset_instance()
    yield
    AvatarManager.reset_instance()
    PluginManager.reset_instance()


@pytest.fixture
def avatar_settings() -> AvatarSettings:
    return AvatarSettings(
        enabled=True,
        fps=30,
        idle_timeout=30,
        blink_interval="random",
        lipsync=True,
    )


@pytest.fixture
def patched_settings(avatar_settings: AvatarSettings):
    patches = [
        patch("ottomandevice.plugins.avatar.manager.settings"),
        patch("ottomandevice.plugins.avatar.plugin.settings"),
    ]
    mocks = [item.start() for item in patches]
    for mock in mocks:
        mock.avatar = avatar_settings
    yield avatar_settings
    for item in patches:
        item.stop()


@pytest.fixture
def renderer() -> MockAvatarRenderer:
    return MockAvatarRenderer()


def _manager(bus: EventBus, renderer: MockAvatarRenderer) -> AvatarManager:
    return AvatarManager.get_instance(event_bus=bus, renderer=renderer)


def _loud_pcm() -> bytes:
    samples = [18000] * 128
    return struct.pack(f"<{len(samples)}h", *samples)


def test_state_machine_valid_transitions() -> None:
    machine = AvatarStateMachine()
    assert machine.state == AvatarState.BOOTING
    assert machine.transition(AvatarState.IDLE, reason="boot") is True
    assert machine.transition(AvatarState.LISTENING, reason="listen") is True
    assert machine.transition(AvatarState.SPEAKING, reason="invalid") is False


def test_state_machine_force() -> None:
    changes: list[tuple[str, str]] = []

    def on_change(previous: AvatarState, current: AvatarState, reason: str) -> None:
        changes.append((previous.value, current.value))

    machine = AvatarStateMachine(on_change=on_change)
    machine.force(AvatarState.ERROR, reason="test")
    assert machine.state == AvatarState.ERROR
    assert changes == [("booting", "error")]


def test_lipsync_analyzes_pcm() -> None:
    engine = LipSyncEngine()
    silent = engine.analyze_pcm(b"\x00\x00" * 64)
    loud = engine.analyze_pcm(_loud_pcm())
    assert silent.mouth_openness == 0.0
    assert loud.mouth_openness > silent.mouth_openness


def test_emotion_engine_maps_state() -> None:
    engine = EmotionEngine()
    assert engine.map_state(AvatarState.THINKING) == Emotion.THINKING
    assert engine.map_state(AvatarState.SLEEPING) == Emotion.SLEEPY
    assert "smile" in engine.blend_shapes(Emotion.HAPPY)


def test_animation_queue_and_interrupt() -> None:
    controller = AnimationController()
    started: list[str] = []
    completed: list[str] = []
    controller.set_callbacks(on_started=started.append, on_completed=completed.append)
    controller.enqueue(AnimationRequest(priority=0, name="idle", duration_ms=1000.0, loop=True))
    assert controller.tick() == "idle"
    controller.enqueue_front(AnimationRequest(priority=10, name="blink", duration_ms=100.0))
    controller.interrupt()
    assert controller.current is None
    assert controller.queue_size == 0


@pytest.mark.asyncio
async def test_renderer_abstraction(renderer: MockAvatarRenderer) -> None:
    await renderer.initialize(target_fps=60)
    await renderer.load_avatar("test")
    frame = AvatarRenderFrame(
        state=AvatarState.IDLE,
        emotion="neutral",
        animation="idle",
        mouth_openness=0.0,
        viseme="neutral",
    )
    await renderer.render(frame)
    assert len(renderer.frames) == 1
    await renderer.shutdown()


def test_avatar_loaded_event(
    bus: EventBus,
    patched_settings,
    renderer: MockAvatarRenderer,
) -> None:
    events: list[str] = []
    bus.subscribe("AvatarLoaded", lambda event: events.append(event.event_type))

    manager = _manager(bus, renderer)
    manager.start()
    time.sleep(0.3)
    assert "AvatarLoaded" in events
    assert manager.state == AvatarState.IDLE
    manager.shutdown()


def test_state_changed_on_speech_listening(
    bus: EventBus,
    patched_settings,
    renderer: MockAvatarRenderer,
) -> None:
    states: list[str] = []
    bus.subscribe(
        "AvatarStateChanged",
        lambda event: states.append(event.payload["current_state"]),
    )

    manager = _manager(bus, renderer)
    manager.start()
    time.sleep(0.2)
    bus.publish(SpeechListeningStarted(provider="whisper"))
    time.sleep(0.1)
    assert AvatarState.LISTENING.value in states
    manager.shutdown()


def test_speech_playback_transitions_to_speaking(
    bus: EventBus,
    patched_settings,
    renderer: MockAvatarRenderer,
) -> None:
    manager = _manager(bus, renderer)
    manager.start()
    time.sleep(0.2)
    bus.publish(SpeechPlaybackStarted(request_id="r1", provider="elevenlabs", text_length=12))
    time.sleep(0.1)
    assert manager.state == AvatarState.SPEAKING
    bus.publish(
        SpeechPlaybackCompleted(
            request_id="r1",
            provider="elevenlabs",
            duration_ms=100.0,
            bytes_played=1024,
        )
    )
    time.sleep(0.1)
    assert manager.state == AvatarState.IDLE
    manager.shutdown()


def test_ai_request_transitions_to_thinking(
    bus: EventBus,
    patched_settings,
    renderer: MockAvatarRenderer,
) -> None:
    manager = _manager(bus, renderer)
    manager.start()
    time.sleep(0.2)
    bus.publish(AIRequestStarted(request_id="a1", session_id="s1", provider="openai"))
    time.sleep(0.1)
    assert manager.state == AvatarState.THINKING
    manager.shutdown()


def test_animation_events(
    bus: EventBus,
    patched_settings,
    renderer: MockAvatarRenderer,
) -> None:
    started: list[str] = []
    completed: list[str] = []
    bus.subscribe("AvatarAnimationStarted", lambda event: started.append(event.payload["animation"]))
    bus.subscribe(
        "AvatarAnimationCompleted",
        lambda event: completed.append(event.payload["animation"]),
    )

    manager = _manager(bus, renderer)
    manager.start()
    time.sleep(0.2)
    controller = manager.animation_controller
    controller.interrupt()
    controller.enqueue(AnimationRequest(priority=5, name="wave", duration_ms=50.0, loop=False))
    time.sleep(0.2)
    assert "wave" in started
    assert "wave" in completed
    manager.shutdown()


def test_lipsync_driven_rendering(
    bus: EventBus,
    patched_settings,
    renderer: MockAvatarRenderer,
) -> None:
    mock_speech = MagicMock()
    mock_speech.playback_buffer = AudioBuffer()
    mock_speech.playback_buffer.append(_loud_pcm())

    manager = _manager(bus, renderer)
    with patch(
        "ottomandevice.plugins.speech.manager.SpeechManager.get_instance_optional",
        return_value=mock_speech,
    ):
        manager.start()
        time.sleep(0.2)
        bus.publish(SpeechPlaybackStarted(request_id="r1", provider="elevenlabs", text_length=8))
        time.sleep(0.3)
        speaking_frames = [frame for frame in renderer.frames if frame.state == AvatarState.SPEAKING]
        assert speaking_frames
        assert any(frame.mouth_openness > 0.0 for frame in speaking_frames)
    manager.shutdown()


def test_interruptible_animations(
    bus: EventBus,
    patched_settings,
    renderer: MockAvatarRenderer,
) -> None:
    manager = _manager(bus, renderer)
    manager.start()
    time.sleep(0.2)
    controller = manager.animation_controller
    controller.enqueue(AnimationRequest(priority=0, name="long", duration_ms=5000.0, loop=True))
    controller.tick()
    controller.interrupt()
    assert controller.current is None
    manager.shutdown()


def test_fps_monitoring(
    bus: EventBus,
    patched_settings,
    renderer: MockAvatarRenderer,
) -> None:
    manager = _manager(bus, renderer)
    manager.start()
    time.sleep(0.5)
    report = manager.health_report()
    assert report["target_fps"] == 30
    assert report["fps"] >= 0.0
    manager.shutdown()


def test_plugin_metadata() -> None:
    plugin = OttomanAvatarPlugin()
    assert plugin.metadata.id == "avatar"


def test_plugin_starts_without_renderer_failure(bus: EventBus, patched_settings) -> None:
    failing = MockAvatarRenderer()

    async def fail_load(asset_id: str = "default") -> None:
        raise RuntimeError("load failed")

    failing.load_avatar = fail_load  # type: ignore[method-assign]

    plugin = OttomanAvatarPlugin()
    plugin.install()
    with patch.object(
        AvatarManager,
        "get_instance",
        return_value=AvatarManager(event_bus=bus, renderer=failing),
    ):
        plugin.initialize()
        plugin.start()
    plugin.stop()
    plugin.uninstall()


def test_avatar_plugin_discovered(bus: EventBus) -> None:
    import importlib
    from pathlib import Path

    package = importlib.import_module("ottomandevice.plugins")
    plugins_root = Path(package.__path__[0])
    manager = PluginManager(plugins_root=plugins_root, event_bus=bus)
    discovered = manager.discover()
    assert "avatar" in discovered


def test_cloud_avatar_health_snapshot(
    bus: EventBus,
    patched_settings,
    renderer: MockAvatarRenderer,
) -> None:
    from ottomandevice.cloud.device_manager import _avatar_health_snapshot

    manager = _manager(bus, renderer)
    manager.start()
    time.sleep(0.2)
    snapshot = _avatar_health_snapshot()
    assert snapshot is not None
    assert snapshot["backend"] == "mock"
    manager.shutdown()


def test_idle_timeout_transitions_to_sleeping(
    bus: EventBus,
    avatar_settings: AvatarSettings,
    renderer: MockAvatarRenderer,
) -> None:
    fast_idle = AvatarSettings(
        enabled=True,
        fps=30,
        idle_timeout=0,
        blink_interval="random",
        lipsync=True,
    )
    with patch("ottomandevice.plugins.avatar.manager.settings") as mock_settings:
        mock_settings.avatar = fast_idle
        manager = _manager(bus, renderer)
        manager.start()
        time.sleep(0.5)
        assert manager.state == AvatarState.SLEEPING
        manager.shutdown()
