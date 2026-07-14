from __future__ import annotations

import asyncio
import enum
import threading
import time
from typing import Any

from ottomandevice.runtime.context import SessionContext
from ottomandevice.runtime.metrics import SessionMetrics
from ottomandevice.runtime.pipeline import InteractionPipeline, PipelineStage


class SessionLifecycle(str, enum.Enum):
    """Lifecycle states for a runtime session."""

    STARTING = "starting"
    ACTIVE = "active"
    IDLE = "idle"
    RECOVERING = "recovering"
    FAILED = "failed"
    ENDED = "ended"


class RuntimeSession:
    """Single digital-human runtime session with recovery and cancellation."""

    def __init__(
        self,
        *,
        context: SessionContext,
        metrics: SessionMetrics,
        pipeline: InteractionPipeline,
        recovery_attempts: int = 2,
        idle_timeout: int = 120,
        on_end: Any | None = None,
    ) -> None:
        self._context = context
        self._metrics = metrics
        self._pipeline = pipeline
        self._recovery_attempts = recovery_attempts
        self._idle_timeout = idle_timeout
        self._on_end = on_end
        self._lock = threading.RLock()
        self._lifecycle = SessionLifecycle.STARTING
        self._interaction_task: asyncio.Task[SessionContext] | None = None
        self._idle_monitor_task: asyncio.Task[None] | None = None

    @property
    def context(self) -> SessionContext:
        return self._context

    @property
    def metrics(self) -> SessionMetrics:
        return self._metrics

    @property
    def lifecycle(self) -> SessionLifecycle:
        with self._lock:
            return self._lifecycle

    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._lifecycle in {
                SessionLifecycle.STARTING,
                SessionLifecycle.ACTIVE,
                SessionLifecycle.IDLE,
                SessionLifecycle.RECOVERING,
            }

    async def activate(self) -> None:
        with self._lock:
            self._lifecycle = SessionLifecycle.ACTIVE
        self._idle_monitor_task = asyncio.create_task(self._monitor_idle_timeout())

    async def run_interaction(self, *, pcm: bytes) -> SessionContext:
        with self._lock:
            if self._lifecycle == SessionLifecycle.ENDED:
                raise RuntimeError("Session has ended")
            self._lifecycle = SessionLifecycle.ACTIVE
        self._context.touch()
        try:
            result = await self._pipeline.run(pcm=pcm)
            with self._lock:
                self._lifecycle = SessionLifecycle.IDLE
            return result
        except asyncio.CancelledError:
            with self._lock:
                self._lifecycle = SessionLifecycle.IDLE
            raise
        except Exception:
            self._metrics.record_failure()
            recovered = await self.recover(last_pcm=pcm)
            if recovered:
                return self._context
            with self._lock:
                self._lifecycle = SessionLifecycle.FAILED
            raise

    async def recover(self, *, last_pcm: bytes | None = None) -> bool:
        with self._lock:
            if self._lifecycle == SessionLifecycle.ENDED:
                return False
            self._lifecycle = SessionLifecycle.RECOVERING

        for _attempt in range(self._recovery_attempts):
            try:
                if last_pcm:
                    await self._pipeline.run(pcm=last_pcm)
                else:
                    with self._lock:
                        self._lifecycle = SessionLifecycle.IDLE
                    return True
                self._metrics.record_recovery()
                with self._lock:
                    self._lifecycle = SessionLifecycle.IDLE
                return True
            except Exception:
                continue

        with self._lock:
            self._lifecycle = SessionLifecycle.FAILED
        return False

    async def cancel(self) -> None:
        await self._pipeline.cancel()
        if self._interaction_task is not None and not self._interaction_task.done():
            self._interaction_task.cancel()
            try:
                await self._interaction_task
            except asyncio.CancelledError:
                pass
        with self._lock:
            if self._lifecycle != SessionLifecycle.FAILED:
                self._lifecycle = SessionLifecycle.IDLE

    async def end(self) -> None:
        await self.cancel()
        if self._idle_monitor_task is not None and not self._idle_monitor_task.done():
            self._idle_monitor_task.cancel()
            try:
                await self._idle_monitor_task
            except asyncio.CancelledError:
                pass
        self._metrics.finalize()
        with self._lock:
            self._lifecycle = SessionLifecycle.ENDED
        if self._on_end is not None:
            self._on_end(self)

    async def _monitor_idle_timeout(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            with self._lock:
                lifecycle = self._lifecycle
            if lifecycle in {SessionLifecycle.ENDED, SessionLifecycle.FAILED}:
                return
            if lifecycle == SessionLifecycle.IDLE and self._context.idle_seconds() >= self._idle_timeout:
                await self.end()
                return
