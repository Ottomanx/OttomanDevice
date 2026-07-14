from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class QueuedJob:
    transfer_id: str
    coro_factory: Callable[[], Awaitable[Any]]


class TransferWorkerPool:
    """Unlimited queue with a fixed number of concurrent workers."""

    def __init__(self, *, max_workers: int = 2) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._max_workers = max_workers
        self._queue: deque[QueuedJob] = deque()
        self._active_workers = 0
        self._lock = asyncio.Lock()
        self._wakeup = asyncio.Event()

    @property
    def queued_count(self) -> int:
        return len(self._queue)

    @property
    def active_workers(self) -> int:
        return self._active_workers

    async def submit(self, transfer_id: str, coro_factory: Callable[[], Awaitable[Any]]) -> None:
        async with self._lock:
            self._queue.append(QueuedJob(transfer_id=transfer_id, coro_factory=coro_factory))
            self._wakeup.set()
        await self._ensure_workers()

    async def _ensure_workers(self) -> None:
        async with self._lock:
            while self._active_workers < self._max_workers and self._queue:
                job = self._queue.popleft()
                self._active_workers += 1
                asyncio.create_task(self._run_job(job))

    async def _run_job(self, job: QueuedJob) -> None:
        try:
            await job.coro_factory()
        finally:
            async with self._lock:
                self._active_workers -= 1
                if not self._queue and self._active_workers == 0:
                    self._wakeup.clear()
            await self._ensure_workers()

    async def cancel_pending(self, transfer_id: str) -> bool:
        async with self._lock:
            before = len(self._queue)
            self._queue = deque(
                job for job in self._queue if job.transfer_id != transfer_id
            )
            return len(self._queue) != before
