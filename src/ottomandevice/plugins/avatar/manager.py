from __future__ import annotations

import asyncio
import random
import threading
import time
from collections import deque
from typing import Any

from ottomandevice.config import settings
from ottomandevice.core.event_bus import (
    AIRequestCompleted,
    AIRequestFailed,
    AIRequestStarted,
    AIResponseStreamCompleted,
    AIResponseStreamStarted,
    AvatarAnimationCompleted,
    AvatarAnimationStarted,
    AvatarError,
    AvatarLoaded,
    AvatarStateChanged,
    CameraFrameCaptured,
    EventBus,
    SpeechListeningStarted,
    SpeechListeningStopped,
    SpeechPlaybackCompleted,
    SpeechPlaybackInterrupted,
    SpeechPlaybackStarted,
    SpeechRecognitionFailed,
)
from ottomandevice.plugins.avatar.animation import AnimationController, AnimationRequest
from ottomandevice.plugins.avatar.emotion import EmotionEngine
from ottomandevice.plugins.avatar.lipsync import LipSyncEngine, LipSyncFrame
from ottomandevice.plugins.avatar.renderer import AvatarRenderFrame, AvatarRenderer, HeadlessAvatarRenderer
from ottomandevice.plugins.avatar.state import AvatarState, AvatarStateMachine


class AvatarManager:
    """Orchestrates avatar rendering, animation, lip sync, and event integration."""

    _instance: AvatarManager | None = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        renderer: AvatarRenderer | None = None,
    ) -> None:
        self._event_bus = event_bus or EventBus.get_instance()
        self._lock = threading.RLock()
        self._renderer = renderer or HeadlessAvatarRenderer()
        self._state_machine = AvatarStateMachine(on_change=self._on_state_changed)
        self._emotion = EmotionEngine()
        self._lipsync = LipSyncEngine(enabled=settings.avatar.lipsync)
        self._animation = AnimationController()
        self._animation.set_callbacks(
            on_started=self._on_animation_started,
            on_completed=self._on_animation_completed,
        )
        self._subscriptions: list[str] = []
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._render_task: asyncio.Task[None] | None = None
        self._started = False
        self._last_activity = time.monotonic()
        self._next_blink = time.monotonic() + self._random_blink_delay()
        self._frame_times: deque[float] = deque(maxlen=120)
        self._last_lipsync = LipSyncFrame(mouth_openness=0.0)

    @classmethod
    def get_instance(
        cls,
        *,
        event_bus: EventBus | None = None,
        renderer: AvatarRenderer | None = None,
    ) -> AvatarManager:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(event_bus=event_bus, renderer=renderer)
            return cls._instance

    @classmethod
    def get_instance_optional(cls) -> AvatarManager | None:
        with cls._instance_lock:
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    @property
    def state(self) -> AvatarState:
        return self._state_machine.state

    @property
    def renderer(self) -> AvatarRenderer:
        return self._renderer

    @property
    def animation_controller(self) -> AnimationController:
        return self._animation

    @property
    def lipsync_engine(self) -> LipSyncEngine:
        return self._lipsync

    @property
    def emotion_engine(self) -> EmotionEngine:
        return self._emotion

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._run_loop,
                name="avatar-runtime-loop",
                daemon=True,
            )
            self._loop_thread.start()
            self._started = True
        self.run_coroutine(self._bootstrap())

    def shutdown(self) -> None:
        with self._lock:
            if not self._started:
                return
            loop = self._loop
            thread = self._loop_thread
            self._started = False
        if loop is not None:
            future = asyncio.run_coroutine_threadsafe(self._shutdown_runtime(), loop)
            try:
                future.result(timeout=10)
            except Exception:
                pass
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        self._unsubscribe_events()
        with self._lock:
            self._loop = None
            self._loop_thread = None

    def run_coroutine(self, coro: Any) -> Any:
        loop = self._require_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=120)

    async def transition(self, target: AvatarState, *, reason: str = "") -> bool:
        return self._state_machine.transition(target, reason=reason)

    def current_fps(self) -> float:
        with self._lock:
            if len(self._frame_times) < 2:
                return 0.0
            elapsed = self._frame_times[-1] - self._frame_times[0]
            if elapsed <= 0:
                return 0.0
            return (len(self._frame_times) - 1) / elapsed

    def health_report(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "backend": self._renderer.backend,
            "fps": round(self.current_fps(), 2),
            "target_fps": settings.avatar.fps,
            "animation": self._animation.current.name if self._animation.current else None,
            "queue_size": self._animation.queue_size,
            "emotion": self._emotion.map_state(self.state).value,
        }

    def _run_loop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None:
            raise RuntimeError("Avatar manager event loop is not running")
        return loop

    async def _bootstrap(self) -> None:
        try:
            await self._renderer.initialize(target_fps=settings.avatar.fps)
            await self._renderer.load_avatar("default")
            self._subscribe_events()
            self._state_machine.transition(AvatarState.IDLE, reason="loaded")
            self._publish(
                AvatarLoaded(
                    backend=self._renderer.backend,
                    asset_id="default",
                )
            )
            self._animation.enqueue(self._animation.idle_animation())
            self._render_task = asyncio.create_task(self._render_loop())
        except Exception as exc:
            self._state_machine.force(AvatarState.ERROR, reason=str(exc))
            self._publish(AvatarError(error=str(exc), state=self.state.value))

    async def _shutdown_runtime(self) -> None:
        if self._render_task is not None and not self._render_task.done():
            self._render_task.cancel()
            try:
                await self._render_task
            except asyncio.CancelledError:
                pass
        await self._renderer.shutdown()

    async def _render_loop(self) -> None:
        frame_interval = 1.0 / max(1, settings.avatar.fps)
        while True:
            started = time.perf_counter()
            await self._render_frame()
            with self._lock:
                self._frame_times.append(time.perf_counter())
            elapsed = time.perf_counter() - started
            await asyncio.sleep(max(0.0, frame_interval - elapsed))

    async def _render_frame(self) -> None:
        self._handle_idle_timeout()
        self._maybe_schedule_blink()
        animation_name = self._animation.tick()
        if animation_name is None and self.state in {AvatarState.IDLE, AvatarState.SLEEPING}:
            self._animation.enqueue(self._animation.idle_animation())
            animation_name = self._animation.tick()

        lip_frame = await self._resolve_lipsync()
        emotion = self._emotion.map_state(self.state)
        blend_shapes = self._emotion.blend_shapes(emotion)
        blend_shapes["mouth_open"] = lip_frame.mouth_openness

        frame = AvatarRenderFrame(
            state=self.state,
            emotion=emotion.value,
            animation=animation_name,
            mouth_openness=lip_frame.mouth_openness,
            viseme=lip_frame.viseme,
            blend_shapes=blend_shapes,
        )
        await self._renderer.render(frame)

    async def _resolve_lipsync(self) -> LipSyncFrame:
        if not settings.avatar.lipsync or self.state != AvatarState.SPEAKING:
            return LipSyncFrame(mouth_openness=0.0, viseme="neutral")

        pcm = self._read_speech_audio()
        if pcm:
            self._last_lipsync = self._lipsync.analyze_pcm(pcm)
        return self._last_lipsync

    def _read_speech_audio(self) -> bytes:
        try:
            from ottomandevice.plugins.speech.manager import SpeechManager

            speech = SpeechManager.get_instance_optional()
            if speech is None:
                return b""
            buffer = speech.playback_buffer
            if buffer.size == 0:
                return b""
            return buffer.drain()
        except Exception:
            return b""

    def _handle_idle_timeout(self) -> None:
        if self.state != AvatarState.IDLE:
            return
        if time.monotonic() - self._last_activity >= settings.avatar.idle_timeout:
            self._state_machine.transition(AvatarState.SLEEPING, reason="idle_timeout")

    def _maybe_schedule_blink(self) -> None:
        if self.state in {AvatarState.ERROR, AvatarState.BOOTING}:
            return
        if time.monotonic() < self._next_blink:
            return
        self._animation.enqueue_front(self._animation.blink_animation())
        self._next_blink = time.monotonic() + self._random_blink_delay()

    def _random_blink_delay(self) -> float:
        if settings.avatar.blink_interval == "random":
            return random.uniform(2.0, 6.0)
        try:
            return float(settings.avatar.blink_interval)
        except (TypeError, ValueError):
            return 4.0

    def _touch_activity(self) -> None:
        self._last_activity = time.monotonic()
        if self.state == AvatarState.SLEEPING:
            self._state_machine.transition(AvatarState.IDLE, reason="activity")

    def _subscribe_events(self) -> None:
        bindings = [
            ("SpeechListeningStarted", self._on_speech_listening_started),
            ("SpeechListeningStopped", self._on_speech_listening_stopped),
            ("SpeechPlaybackStarted", self._on_speech_playback_started),
            ("SpeechPlaybackCompleted", self._on_speech_playback_completed),
            ("SpeechPlaybackInterrupted", self._on_speech_playback_interrupted),
            ("SpeechRecognitionFailed", self._on_speech_recognition_failed),
            ("AIRequestStarted", self._on_ai_request_started),
            ("AIRequestCompleted", self._on_ai_request_completed),
            ("AIRequestFailed", self._on_ai_request_failed),
            ("AIResponseStreamStarted", self._on_ai_stream_started),
            ("AIResponseStreamCompleted", self._on_ai_stream_completed),
            ("CameraFrameCaptured", self._on_camera_frame),
        ]
        for event_type, handler in bindings:
            self._subscriptions.append(self._event_bus.subscribe(event_type, handler))

    def _unsubscribe_events(self) -> None:
        for subscription_id in self._subscriptions:
            self._event_bus.unsubscribe(subscription_id)
        self._subscriptions.clear()

    def _on_state_changed(self, previous: AvatarState, current: AvatarState, reason: str) -> None:
        self._publish(
            AvatarStateChanged(
                previous_state=previous.value,
                current_state=current.value,
                reason=reason,
            )
        )

    def _on_animation_started(self, name: str) -> None:
        self._publish(AvatarAnimationStarted(animation=name))

    def _on_animation_completed(self, name: str) -> None:
        self._publish(AvatarAnimationCompleted(animation=name))

    def _on_speech_listening_started(self, event: Any) -> None:
        self._touch_activity()
        self._state_machine.transition(AvatarState.LISTENING, reason="speech_listening")

    def _on_speech_listening_stopped(self, event: Any) -> None:
        if self.state == AvatarState.LISTENING:
            self._state_machine.transition(AvatarState.IDLE, reason="speech_listening_stopped")

    def _on_speech_playback_started(self, event: Any) -> None:
        self._touch_activity()
        self._animation.interrupt()
        self._state_machine.transition(AvatarState.SPEAKING, reason="speech_playback")

    def _on_speech_playback_completed(self, event: Any) -> None:
        if self.state == AvatarState.SPEAKING:
            self._state_machine.transition(AvatarState.IDLE, reason="speech_playback_completed")
        self._last_lipsync = LipSyncFrame(mouth_openness=0.0)

    def _on_speech_playback_interrupted(self, event: Any) -> None:
        self._animation.interrupt()
        if self.state == AvatarState.SPEAKING:
            self._state_machine.transition(AvatarState.IDLE, reason="speech_playback_interrupted")

    def _on_speech_recognition_failed(self, event: Any) -> None:
        self._state_machine.transition(AvatarState.ERROR, reason="speech_recognition_failed")

    def _on_ai_request_started(self, event: Any) -> None:
        self._touch_activity()
        self._state_machine.transition(AvatarState.THINKING, reason="ai_request")

    def _on_ai_request_completed(self, event: Any) -> None:
        if self.state == AvatarState.THINKING:
            self._state_machine.transition(AvatarState.IDLE, reason="ai_request_completed")

    def _on_ai_request_failed(self, event: Any) -> None:
        self._state_machine.transition(AvatarState.ERROR, reason="ai_request_failed")

    def _on_ai_stream_started(self, event: Any) -> None:
        self._touch_activity()
        self._state_machine.transition(AvatarState.THINKING, reason="ai_stream")

    def _on_ai_stream_completed(self, event: Any) -> None:
        if self.state == AvatarState.THINKING:
            self._state_machine.transition(AvatarState.IDLE, reason="ai_stream_completed")

    def _on_camera_frame(self, event: Any) -> None:
        self._touch_activity()

    def _publish(self, event: Any) -> None:
        self._event_bus.publish(event)
