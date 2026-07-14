from __future__ import annotations

import asyncio
import os
import threading
from typing import Any

from ottomandevice.config import settings
from ottomandevice.config.settings import RemoteDesktopSettings, Settings
from ottomandevice.desktop_stream.capture_engine import CaptureEngine
from ottomandevice.logging import get_logger
from ottomandevice.remote_desktop.auth import TokenReplayGuard
from ottomandevice.remote_desktop.websocket_server import RemoteDesktopWebSocketServer
from ottomandevice.runtime import get_device_id

logger = get_logger("remote_desktop")


class RemoteDesktopService:
    def __init__(
        self,
        *,
        app_settings: Settings | None = None,
        device_id: str | None = None,
        jwt_secret: str | None = None,
        remote_desktop_settings: RemoteDesktopSettings | None = None,
        capture_engine: CaptureEngine | None = None,
        desktop_stream_service: Any | None = None,
    ) -> None:
        self._settings = app_settings or settings
        self._remote_desktop_settings = (
            remote_desktop_settings or self._settings.remote_desktop
        )
        self._device_id = device_id or get_device_id()
        self._jwt_secret = (
            jwt_secret
            if jwt_secret is not None
            else os.getenv(self._remote_desktop_settings.jwt_secret_env, "")
        )
        self._replay_guard = TokenReplayGuard()
        self._desktop_stream_service = desktop_stream_service
        self._capture_engine = capture_engine or CaptureEngine(
            target_width=self._remote_desktop_settings.width,
            jpeg_quality=self._remote_desktop_settings.jpeg_quality,
        )
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: RemoteDesktopWebSocketServer | None = None
        self._stop_event = threading.Event()

    @property
    def bound_port(self) -> int | None:
        if self._server is None:
            return None
        return self._server.bound_port

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        if not self._jwt_secret:
            logger.warning(
                "Remote desktop JWT secret not configured; AUTH will reject clients"
            )

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="remote_desktop",
            daemon=True,
        )
        self._thread.start()
        logger.info("Remote desktop service started")

    def stop(self) -> None:
        self._stop_event.set()
        loop = self._loop
        if loop and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._shutdown(), loop)
            try:
                future.result(timeout=self._remote_desktop_settings.disconnect_timeout + 5)
            except Exception:
                logger.exception("Remote desktop service shutdown failed")

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._remote_desktop_settings.disconnect_timeout + 5)

        logger.info("Remote desktop service stopped")

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._startup())
        except Exception:
            logger.exception("Remote desktop service failed")
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.close()
            self._loop = None

    async def _startup(self) -> None:
        self._server = RemoteDesktopWebSocketServer(
            device_id=self._device_id,
            settings=self._remote_desktop_settings,
            jwt_secret=self._jwt_secret,
            capture_engine=self._capture_engine,
            replay_guard=self._replay_guard,
            on_stream_started=self._pause_storage_stream,
            on_stream_stopped=self._resume_storage_stream,
        )
        await self._server.start()
        while not self._stop_event.is_set():
            await asyncio.sleep(0.2)

        await self._shutdown()

    def _pause_storage_stream(self) -> None:
        if self._desktop_stream_service is not None:
            self._desktop_stream_service.stop()

    def _resume_storage_stream(self) -> None:
        if self._desktop_stream_service is not None:
            self._desktop_stream_service.start()

    async def _shutdown(self) -> None:
        if self._server is not None:
            await self._server.stop()
            self._server = None


__all__ = ["RemoteDesktopService", "RemoteDesktopWebSocketServer"]
