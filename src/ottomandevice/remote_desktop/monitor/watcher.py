from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from enum import Enum

from ottomandevice.logging import get_logger
from ottomandevice.remote_desktop.monitor.manager import MonitorManager
from ottomandevice.remote_desktop.monitor.models import MonitorChangeType

logger = get_logger("remote_desktop.monitor.watcher")


class MonitorPollingMode(str, Enum):
    DISABLED = "disabled"
    IDLE = "idle"
    STREAMING = "streaming"


MonitorChangedCallback = Callable[[MonitorChangeType, bool], Awaitable[None]]


class DisplayWatcher:
    def __init__(
        self,
        *,
        manager: MonitorManager,
        streaming_interval_ms: int,
        idle_interval_ms: int,
    ) -> None:
        self._manager = manager
        self._streaming_interval_ms = streaming_interval_ms
        self._idle_interval_ms = idle_interval_ms
        self._mode = MonitorPollingMode.DISABLED

    @property
    def mode(self) -> MonitorPollingMode:
        return self._mode

    def set_mode(self, mode: MonitorPollingMode) -> None:
        self._mode = mode

    async def run(
        self,
        on_changed: MonitorChangedCallback,
        *,
        should_poll: Callable[[], bool],
        shutdown_event: asyncio.Event,
    ) -> None:
        while not shutdown_event.is_set():
            if self._mode == MonitorPollingMode.DISABLED or not should_poll():
                try:
                    await asyncio.wait_for(shutdown_event.wait(), timeout=0.25)
                    return
                except asyncio.TimeoutError:
                    continue

            interval_ms = self._interval_ms()
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=interval_ms / 1000.0)
                return
            except asyncio.TimeoutError:
                pass

            if self._mode == MonitorPollingMode.DISABLED or not should_poll():
                continue

            change = self._manager.refresh()
            if change is None:
                continue

            fallback = False
            if change == MonitorChangeType.REMOVED:
                fallback = self._manager.handle_active_monitor_removed()

            try:
                await on_changed(change, fallback)
            except Exception:
                logger.info("Monitor change notification failed")

    def _interval_ms(self) -> int:
        if self._mode == MonitorPollingMode.STREAMING:
            return self._streaming_interval_ms
        if self._mode == MonitorPollingMode.IDLE:
            return self._idle_interval_ms
        return self._idle_interval_ms
