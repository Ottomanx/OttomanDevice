from __future__ import annotations

import asyncio
import threading
import uuid
from typing import Any

from ottomandevice.config import settings
from ottomandevice.core.event_bus import (
    EventBus,
    PipelineCompleted,
    SessionEnded,
    SessionFailed,
    SessionRecovered,
    SessionStarted,
)
from ottomandevice.runtime.context import SessionContext
from ottomandevice.runtime.metrics import SessionMetrics
from ottomandevice.runtime.pipeline import InteractionPipeline
from ottomandevice.runtime.session import RuntimeSession, SessionLifecycle


class ComponentBridge:
    """Resolves optional plugin managers for the interaction pipeline."""

    def __init__(
        self,
        *,
        camera: Any | None = None,
        audio: Any | None = None,
        speech: Any | None = None,
        ai: Any | None = None,
        avatar: Any | None = None,
    ) -> None:
        self._camera = camera
        self._audio = audio
        self._speech = speech
        self._ai = ai
        self._avatar = avatar

    @property
    def camera(self) -> Any | None:
        if self._camera is not None:
            return self._camera
        try:
            from ottomandevice.plugins.camera.manager import CameraManager

            return CameraManager.get_instance_optional()
        except Exception:
            return None

    @property
    def audio(self) -> Any | None:
        if self._audio is not None:
            return self._audio
        try:
            from ottomandevice.plugins.audio.manager import AudioManager

            return AudioManager.get_instance_optional()
        except Exception:
            return None

    @property
    def speech(self) -> Any | None:
        if self._speech is not None:
            return self._speech
        try:
            from ottomandevice.plugins.speech.manager import SpeechManager

            return SpeechManager.get_instance_optional()
        except Exception:
            return None

    @property
    def ai(self) -> Any | None:
        if self._ai is not None:
            return self._ai
        try:
            from ottomandevice.plugins.ai.manager import AIManager

            return AIManager.get_instance_optional()
        except Exception:
            return None

    @property
    def avatar(self) -> Any | None:
        if self._avatar is not None:
            return self._avatar
        try:
            from ottomandevice.plugins.avatar.manager import AvatarManager

            return AvatarManager.get_instance_optional()
        except Exception:
            return None


class SessionManager:
    """Orchestrates runtime sessions with concurrency protection and recovery."""

    _instance: SessionManager | None = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        components: ComponentBridge | None = None,
    ) -> None:
        self._event_bus = event_bus or EventBus.get_instance()
        self._components = components or ComponentBridge()
        self._lock = threading.RLock()
        self._active_session: RuntimeSession | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._started = False

    @classmethod
    def get_instance(
        cls,
        *,
        event_bus: EventBus | None = None,
        components: ComponentBridge | None = None,
    ) -> SessionManager:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(event_bus=event_bus, components=components)
            return cls._instance

    @classmethod
    def get_instance_optional(cls) -> SessionManager | None:
        with cls._instance_lock:
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    @property
    def active_session(self) -> RuntimeSession | None:
        with self._lock:
            return self._active_session

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._run_loop,
                name="runtime-session-loop",
                daemon=True,
            )
            self._loop_thread.start()
            self._started = True

    def shutdown(self) -> None:
        with self._lock:
            if not self._started:
                return
            loop = self._loop
            thread = self._loop_thread
            session = self._active_session
            self._started = False
            self._active_session = None
        if session is not None:
            try:
                self.run_coroutine(session.end())
            except Exception:
                pass
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self._loop = None
            self._loop_thread = None

    def run_coroutine(self, coro: Any) -> Any:
        loop = self._require_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=180)

    def start_session(self) -> RuntimeSession:
        with self._lock:
            if self._active_session is not None and self._active_session.is_active:
                raise RuntimeError("Concurrent runtime sessions are not allowed")
            context = SessionContext(session_id=str(uuid.uuid4()))
            metrics = SessionMetrics()
            ai = self._components.ai
            if ai is not None and hasattr(ai, "create_session"):
                conversation = ai.create_session(session_id=context.ai_session_id)
                context.ai_session_id = conversation.session_id
            pipeline = InteractionPipeline(
                self._components,
                context=context,
                metrics=metrics,
            )
            session = RuntimeSession(
                context=context,
                metrics=metrics,
                pipeline=pipeline,
                recovery_attempts=settings.runtime_session.recovery_attempts,
                idle_timeout=settings.runtime_session.idle_timeout,
                on_end=self._on_session_end,
            )
            self._active_session = session
        self._publish(
            SessionStarted(
                session_id=context.session_id,
                ai_session_id=context.ai_session_id,
            )
        )
        self.run_coroutine(session.activate())
        return session

    def end_session(self, session_id: str | None = None) -> None:
        with self._lock:
            session = self._active_session
            if session is None:
                return
            if session_id is not None and session.context.session_id != session_id:
                raise RuntimeError("Session id does not match active session")
        self.run_coroutine(session.end())

    def run_interaction(self, *, pcm: bytes, session_id: str | None = None) -> SessionContext:
        with self._lock:
            session = self._active_session
            if session is None:
                session = self.start_session()
            elif session_id is not None and session.context.session_id != session_id:
                raise RuntimeError("Session id does not match active session")
        try:
            recoveries_before = session.metrics.recoveries
            context = self.run_coroutine(session.run_interaction(pcm=pcm))
            if session.metrics.recoveries > recoveries_before:
                self._publish(
                    SessionRecovered(
                        session_id=context.session_id,
                        recoveries=session.metrics.recoveries,
                    )
                )
            self._publish(
                PipelineCompleted(
                    session_id=context.session_id,
                    total_latency_ms=session.metrics.total_latency_ms,
                    pipeline_stage=context.pipeline_stage,
                )
            )
            return context
        except Exception as exc:
            if session.lifecycle == SessionLifecycle.FAILED:
                self._publish(
                    SessionFailed(
                        session_id=session.context.session_id,
                        error=str(exc),
                        pipeline_stage=session.context.pipeline_stage,
                    )
                )
            raise

    def cancel_active(self) -> None:
        with self._lock:
            session = self._active_session
        if session is not None:
            self.run_coroutine(session.cancel())

    def health_report(self) -> dict[str, Any]:
        with self._lock:
            session = self._active_session
        if session is None:
            return {
                "active": False,
                "pipeline_stage": "idle",
                "metrics": SessionMetrics().to_dict(),
            }
        return {
            "active": session.is_active,
            "session_id": session.context.session_id,
            "lifecycle": session.lifecycle.value,
            "pipeline_stage": session.context.pipeline_stage,
            "duration_seconds": round(session.context.duration_seconds(), 3),
            "metrics": session.metrics.to_dict(),
            "context": session.context.snapshot(),
        }

    def _on_session_end(self, session: RuntimeSession) -> None:
        if session.metrics.recoveries > 0:
            self._publish(
                SessionRecovered(
                    session_id=session.context.session_id,
                    recoveries=session.metrics.recoveries,
                )
            )
        self._publish(
            SessionEnded(
                session_id=session.context.session_id,
                duration_ms=session.metrics.session_duration_ms,
                interactions_completed=session.metrics.interactions_completed,
            )
        )
        with self._lock:
            if self._active_session is session:
                self._active_session = None

    def _run_loop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None:
            raise RuntimeError("Session manager event loop is not running")
        return loop

    def _publish(self, event: Any) -> None:
        self._event_bus.publish(event)
