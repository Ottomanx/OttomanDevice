from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from ottomandevice.config.settings import RemoteDesktopSettings
from ottomandevice.desktop_stream.capture_engine import CaptureEngine
from ottomandevice.logging import get_logger

logger = get_logger("remote_desktop.streaming")

SendMessage = Callable[[str, dict[str, Any] | None], Awaitable[None]]


class DesktopStreamRunner:
    def __init__(
        self,
        *,
        capture_engine: CaptureEngine,
        settings: RemoteDesktopSettings,
    ) -> None:
        self._capture_engine = capture_engine
        self._settings = settings
        self._sequence = 0
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._interval_seconds = 1.0 / settings.fps

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start(self, send_message: SendMessage) -> None:
        if self.is_running:
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run(send_message))

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is None:
            return

        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self, send_message: SendMessage) -> None:
        while not self._stop_event.is_set():
            try:
                frame_bytes, width, height = await asyncio.to_thread(
                    self._capture_engine.capture_and_encode
                )
            except Exception:
                logger.error("Streaming error")
                break

            self._sequence += 1
            try:
                await send_message(
                    "FRAME",
                    {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "width": width,
                        "height": height,
                        "format": "jpeg",
                        "sequence": self._sequence,
                        "data": base64.b64encode(frame_bytes).decode("ascii"),
                    },
                )
            except Exception:
                logger.error("Streaming error")
                break

            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval_seconds)
                break
            except asyncio.TimeoutError:
                continue