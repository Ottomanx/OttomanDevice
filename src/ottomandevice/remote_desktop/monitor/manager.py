from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from ottomandevice.logging import get_logger
from ottomandevice.remote_desktop.input_injector import InputInjector
from ottomandevice.remote_desktop.monitor.enumerator import DisplayEnumerator
from ottomandevice.remote_desktop.monitor.models import MonitorChangeType, MonitorInfo
from ottomandevice.remote_desktop.monitor.telemetry import log_monitor_switch
from ottomandevice.remote_desktop.streaming import DesktopStreamRunner

logger = get_logger("remote_desktop.monitor.manager")

SendMessage = Callable[[str, dict[str, Any] | None], Awaitable[None]]


class MonitorError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class MonitorManager:
    def __init__(
        self,
        *,
        enumerator: DisplayEnumerator,
        capture_engine: Any,
        input_injector: InputInjector,
        immediate_capture: bool = True,
    ) -> None:
        self._enumerator = enumerator
        self._capture_engine = capture_engine
        self._input_injector = input_injector
        self._immediate_capture = immediate_capture
        self._monitors: list[MonitorInfo] = []
        self._selected_id: str | None = None
        self._stream_runner: DesktopStreamRunner | None = None

    @property
    def selected_id(self) -> str | None:
        return self._selected_id

    @property
    def monitors(self) -> list[MonitorInfo]:
        return list(self._monitors)

    def bind_stream_runner(self, stream_runner: DesktopStreamRunner) -> None:
        self._stream_runner = stream_runner

    def refresh(self) -> MonitorChangeType | None:
        previous = {monitor.id: monitor for monitor in self._monitors}
        current_list = self._renumber(self._enumerator.enumerate())
        current = {monitor.id: monitor for monitor in current_list}

        if not previous:
            self._monitors = current_list
            return MonitorChangeType.ADDED if current_list else None

        if set(previous) != set(current):
            removed_selected = self._selected_id not in current
            self._monitors = current_list
            if removed_selected:
                self._select_default()
            return MonitorChangeType.REMOVED

        changed = any(previous[monitor_id] != current[monitor_id] for monitor_id in current)
        self._monitors = current_list
        if changed:
            if self._selected_id in current:
                self._apply_selection(current[self._selected_id])
            return MonitorChangeType.UPDATED
        return None

    async def initialize(self, *, preferred_id: str | None = None) -> None:
        self._monitors = self._renumber(self._enumerator.enumerate())
        if preferred_id and self._find(preferred_id) is not None:
            self._selected_id = preferred_id
        else:
            self._select_default()
        monitor = self._require_selected()
        self._apply_selection(monitor)

    async def send_monitor_list(self, send_message: SendMessage) -> None:
        await send_message("MONITOR_LIST", self._list_payload())

    async def select_monitor(
        self,
        monitor_id: str,
        send_message: SendMessage,
    ) -> None:
        if self._stream_runner is None or not self._stream_runner.is_running:
            log_monitor_switch(
                from_monitor=self._selected_id,
                to_monitor=monitor_id,
                duration_ms=0.0,
                success=False,
            )
            raise MonitorError("STREAM_NOT_ACTIVE", "Monitor selection requires active stream")

        started = time.monotonic()
        previous_id = self._selected_id
        monitor = self._find(monitor_id)
        if monitor is None:
            duration_ms = (time.monotonic() - started) * 1000.0
            log_monitor_switch(
                from_monitor=previous_id,
                to_monitor=monitor_id,
                duration_ms=duration_ms,
                success=False,
            )
            await send_message(
                "MONITOR_SELECT",
                {
                    "monitor_id": monitor_id,
                    "accepted": False,
                    "code": "INVALID_MONITOR",
                    "message": "Monitor not found",
                },
            )
            return

        self._selected_id = monitor.id
        self._apply_selection(monitor)
        if self._immediate_capture and self._stream_runner is not None:
            self._stream_runner.request_immediate_frame()

        duration_ms = (time.monotonic() - started) * 1000.0
        log_monitor_switch(
            from_monitor=previous_id,
            to_monitor=monitor.id,
            duration_ms=duration_ms,
            success=True,
        )
        await send_message(
            "MONITOR_SELECT",
            {
                "monitor_id": monitor.id,
                "accepted": True,
                "number": monitor.number,
                "width": monitor.width,
                "height": monitor.height,
                "orientation": monitor.orientation.value,
                "is_primary": monitor.is_primary,
            },
        )

    async def emit_monitor_changed(
        self,
        send_message: SendMessage,
        change: MonitorChangeType,
        *,
        fallback: bool = False,
    ) -> None:
        previous_selected = self._selected_id
        await send_message(
            "MONITOR_CHANGED",
            {
                "change": change.value,
                "monitors": [monitor.to_payload() for monitor in self._monitors],
                "selected_id": self._selected_id,
                "previous_selected_id": previous_selected,
                "fallback": fallback,
            },
        )

    def _list_payload(self) -> dict[str, Any]:
        return {
            "monitors": [monitor.to_payload() for monitor in self._monitors],
            "selected_id": self._selected_id,
        }

    def _renumber(self, monitors: list[MonitorInfo]) -> list[MonitorInfo]:
        renumbered: list[MonitorInfo] = []
        for index, monitor in enumerate(monitors, start=1):
            renumbered.append(
                MonitorInfo(
                    id=monitor.id,
                    number=index,
                    width=monitor.width,
                    height=monitor.height,
                    x=monitor.x,
                    y=monitor.y,
                    is_primary=monitor.is_primary,
                )
            )
        return renumbered

    def _find(self, monitor_id: str) -> MonitorInfo | None:
        for monitor in self._monitors:
            if monitor.id == monitor_id:
                return monitor
        return None

    def _select_default(self) -> None:
        primary = next((monitor for monitor in self._monitors if monitor.is_primary), None)
        if primary is not None:
            self._selected_id = primary.id
            return
        if self._monitors:
            self._selected_id = self._monitors[0].id
            return
        self._selected_id = None

    def _require_selected(self) -> MonitorInfo:
        if self._selected_id is None:
            raise MonitorError("MONITOR_UNAVAILABLE", "No monitors available")
        monitor = self._find(self._selected_id)
        if monitor is None:
            raise MonitorError("MONITOR_UNAVAILABLE", "Selected monitor unavailable")
        return monitor

    def _apply_selection(self, monitor: MonitorInfo) -> None:
        self._capture_engine.set_active_monitor(monitor)
        self._input_injector.set_monitor_bounds(
            monitor.x,
            monitor.y,
            monitor.width,
            monitor.height,
        )

    def handle_active_monitor_removed(self) -> bool:
        if self._selected_id is not None and self._find(self._selected_id) is not None:
            return False
        self._select_default()
        if self._selected_id is None:
            return True
        monitor = self._require_selected()
        self._apply_selection(monitor)
        if self._immediate_capture and self._stream_runner is not None:
            self._stream_runner.request_immediate_frame()
        return True
