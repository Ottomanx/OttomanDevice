from __future__ import annotations

import asyncio
import time
from typing import Any, Protocol

from ottomandevice.runtime.context import SessionContext
from ottomandevice.runtime.metrics import SessionMetrics


class PipelineStage:
    """Named pipeline stages for the digital-human interaction flow."""

    CAMERA = "camera"
    STT = "stt"
    AI = "ai"
    TTS = "tts"
    AVATAR = "avatar"
    COMPLETED = "completed"
    FAILED = "failed"


class RuntimeComponents(Protocol):
    """Optional runtime component accessors used by the interaction pipeline."""

    @property
    def camera(self) -> Any | None: ...

    @property
    def audio(self) -> Any | None: ...

    @property
    def speech(self) -> Any | None: ...

    @property
    def ai(self) -> Any | None: ...

    @property
    def avatar(self) -> Any | None: ...


class InteractionPipeline:
    """End-to-end Camera -> STT -> AI -> TTS -> Avatar interaction pipeline."""

    def __init__(
        self,
        components: RuntimeComponents,
        *,
        context: SessionContext,
        metrics: SessionMetrics,
    ) -> None:
        self._components = components
        self._context = context
        self._metrics = metrics
        self._cancel_event = asyncio.Event()

    @property
    def cancel_event(self) -> asyncio.Event:
        return self._cancel_event

    async def run(self, *, pcm: bytes) -> SessionContext:
        """Execute the full interaction pipeline."""
        self._cancel_event.clear()
        try:
            await self._run_camera_stage()
            self._check_cancelled()
            await self._run_stt_stage(pcm)
            self._check_cancelled()
            await self._run_ai_stage()
            self._check_cancelled()
            await self._run_tts_stage()
            self._check_cancelled()
            await self._run_avatar_stage()
            self._context.set_stage(PipelineStage.COMPLETED)
            self._metrics.set_stage(PipelineStage.COMPLETED)
            return self._context
        except asyncio.CancelledError:
            self._context.set_stage(PipelineStage.FAILED)
            self._metrics.set_stage(PipelineStage.FAILED)
            raise
        except Exception:
            self._context.set_stage(PipelineStage.FAILED)
            self._metrics.set_stage(PipelineStage.FAILED)
            raise

    async def cancel(self) -> None:
        self._cancel_event.set()
        speech = self._components.speech
        if speech is not None and hasattr(speech, "pipeline"):
            try:
                await self._delegate(speech, speech.pipeline.interrupt_playback())
            except Exception:
                pass

    async def _run_camera_stage(self) -> None:
        self._context.set_stage(PipelineStage.CAMERA)
        self._metrics.set_stage(PipelineStage.CAMERA)
        camera = self._components.camera
        if camera is None or not hasattr(camera, "capture_frame"):
            return
        try:
            result = await asyncio.to_thread(camera.capture_frame)
            if getattr(result, "success", False):
                self._context.camera_frame_number = int(getattr(result, "frame_number", 0))
                self._context.touch()
        except Exception:
            return

    async def _run_stt_stage(self, pcm: bytes) -> None:
        speech = self._require_speech()
        self._context.set_stage(PipelineStage.STT)
        self._metrics.set_stage(PipelineStage.STT)
        started = time.perf_counter()
        await self._delegate(speech, speech.start_listening())
        await self._delegate(speech, speech.pipeline.ingest_audio(pcm))
        transcript = await self._delegate(speech, speech.pipeline.recognize_buffered())
        await self._delegate(speech, speech.stop_listening())
        self._metrics.stt_latency_ms = (time.perf_counter() - started) * 1000
        self._context.transcript = transcript
        self._context.touch()
        if not transcript:
            raise RuntimeError("Speech recognition produced no transcript")

    async def _run_ai_stage(self) -> None:
        ai = self._require_ai()
        self._context.set_stage(PipelineStage.AI)
        self._metrics.set_stage(PipelineStage.AI)
        started = time.perf_counter()
        response = await self._delegate(ai, ai.complete(self._context.ai_session_id, self._context.transcript))
        self._metrics.ai_latency_ms = (time.perf_counter() - started) * 1000
        self._context.ai_response = response.text
        self._context.touch()

    async def _run_tts_stage(self) -> None:
        speech = self._require_speech()
        self._context.set_stage(PipelineStage.TTS)
        self._metrics.set_stage(PipelineStage.TTS)
        started = time.perf_counter()
        await self._delegate(speech, speech.pipeline.speak(self._context.ai_response))
        self._metrics.tts_latency_ms = (time.perf_counter() - started) * 1000
        self._context.touch()

    async def _run_avatar_stage(self) -> None:
        self._context.set_stage(PipelineStage.AVATAR)
        self._metrics.set_stage(PipelineStage.AVATAR)
        started = time.perf_counter()
        avatar = self._components.avatar
        if avatar is not None and hasattr(avatar, "state"):
            self._context.metadata["avatar_state"] = getattr(avatar, "state", None)
        self._metrics.avatar_latency_ms = (time.perf_counter() - started) * 1000
        self._metrics.record_interaction(
            stt_ms=self._metrics.stt_latency_ms,
            ai_ms=self._metrics.ai_latency_ms,
            tts_ms=self._metrics.tts_latency_ms,
            avatar_ms=self._metrics.avatar_latency_ms,
        )
        self._context.touch()

    def _require_speech(self) -> Any:
        speech = self._components.speech
        if speech is None:
            raise RuntimeError("Speech runtime is not available")
        return speech

    def _require_ai(self) -> Any:
        ai = self._components.ai
        if ai is None:
            raise RuntimeError("AI runtime is not available")
        return ai

    def _check_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise asyncio.CancelledError()

    @staticmethod
    async def _delegate(manager: Any, coro: Any) -> Any:
        if hasattr(manager, "run_coroutine"):
            return await asyncio.to_thread(manager.run_coroutine, coro)
        if asyncio.iscoroutine(coro):
            return await coro
        return coro
