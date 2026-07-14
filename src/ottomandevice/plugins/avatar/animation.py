from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable


AnimationCallback = Callable[[str], None]


@dataclass(order=True)
class AnimationRequest:
    """Queued animation instruction."""

    priority: int
    name: str = field(compare=False)
    duration_ms: float = field(compare=False, default=1000.0)
    loop: bool = field(compare=False, default=False)
    interruptible: bool = field(compare=False, default=True)


class AnimationController:
    """Thread-safe animation queue with interrupt support."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._queue: deque[AnimationRequest] = deque()
        self._current: AnimationRequest | None = None
        self._started_at: float = 0.0
        self._interrupt = asyncio.Event()
        self._on_started: AnimationCallback | None = None
        self._on_completed: AnimationCallback | None = None

    @property
    def current(self) -> AnimationRequest | None:
        with self._lock:
            return self._current

    @property
    def queue_size(self) -> int:
        with self._lock:
            return len(self._queue)

    def set_callbacks(
        self,
        *,
        on_started: AnimationCallback | None = None,
        on_completed: AnimationCallback | None = None,
    ) -> None:
        self._on_started = on_started
        self._on_completed = on_completed

    def enqueue(self, request: AnimationRequest) -> None:
        with self._lock:
            self._queue.append(request)

    def enqueue_front(self, request: AnimationRequest) -> None:
        with self._lock:
            self._queue.appendleft(request)

    def clear(self) -> None:
        with self._lock:
            self._queue.clear()

    def interrupt(self) -> None:
        self._interrupt.set()
        with self._lock:
            if self._current is not None and self._current.interruptible:
                if self._on_completed is not None:
                    self._on_completed(self._current.name)
                self._current = None
            self._queue.clear()
        self._interrupt.clear()

    def tick(self) -> str | None:
        """Advance animation timeline and return active animation name."""
        now = time.perf_counter()
        with self._lock:
            if self._current is None:
                if not self._queue:
                    return None
                self._current = self._queue.popleft()
                self._started_at = now
                if self._on_started is not None:
                    self._on_started(self._current.name)

            assert self._current is not None
            elapsed_ms = (now - self._started_at) * 1000
            if elapsed_ms >= self._current.duration_ms:
                completed = self._current.name
                if self._on_completed is not None:
                    self._on_completed(completed)
                if self._current.loop:
                    self._started_at = now
                    return self._current.name
                self._current = None
                return self.tick()
            return self._current.name

    def idle_animation(self) -> AnimationRequest:
        return AnimationRequest(priority=0, name="idle_breathe", duration_ms=3000.0, loop=True)

    def blink_animation(self) -> AnimationRequest:
        return AnimationRequest(
            priority=10,
            name="blink",
            duration_ms=150.0,
            loop=False,
            interruptible=True,
        )
