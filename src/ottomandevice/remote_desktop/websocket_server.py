from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from websockets.asyncio.server import Server, serve
from websockets.exceptions import ConnectionClosed
from websockets.typing import Subprotocol

from ottomandevice.config.settings import RemoteDesktopSettings
from ottomandevice.desktop_stream.capture_engine import CaptureEngine
from ottomandevice.logging import get_logger
from ottomandevice.permissions import Permission, has_permission
from ottomandevice.remote_desktop.auth import (
    TokenReplayGuard,
    TokenValidationError,
    validate_session_token,
)
from ottomandevice.remote_desktop.clipboard_sync import (
    ClipboardManager,
    ClipboardPoller,
    parse_clipboard_text,
)
from ottomandevice.remote_desktop.file_transfer import (
    Base64TransferTransport,
    FileTransferError,
    FixedChunkSizeStrategy,
    TransferManager,
    TransferTransport,
    validate_relative_path,
)
from ottomandevice.remote_desktop.file_transfer.path_validator import parse_sha256
from ottomandevice.remote_desktop.file_transfer.queue import TransferWorkerPool
from ottomandevice.remote_desktop.input_injector import (
    InputInjector,
    extract_mouse_fields,
    parse_normalized_coordinate_strict,
    parse_scroll_delta,
)
from ottomandevice.remote_desktop.keyboard_injector import (
    KeyboardInjector,
    parse_key,
    parse_text_input,
)
from ottomandevice.remote_desktop.monitor import (
    DisplayWatcher,
    MonitorError,
    MonitorManager,
    MonitorPollingMode,
    default_display_enumerator,
)
from ottomandevice.remote_desktop.monitor.enumerator import DisplayEnumerator
from ottomandevice.remote_desktop.session import RemoteDesktopSession, SessionState
from ottomandevice.remote_desktop.streaming import DesktopStreamRunner

logger = get_logger("remote_desktop.websocket_server")

NOT_IMPLEMENTED_TYPES = frozenset(
    {
        "MOUSE",
    }
)

mouse_logger = get_logger("remote_desktop.mouse")
keyboard_logger = get_logger("remote_desktop.keyboard")
clipboard_logger = get_logger("remote_desktop.clipboard")
file_logger = get_logger("remote_desktop.file_transfer")
monitor_logger = get_logger("remote_desktop.monitor")
session_logger = get_logger("remote_desktop.session")


def _session_info_payload(session: RemoteDesktopSession | None) -> dict[str, Any]:
    if session is None or not session.is_active or session.started_at_ms is None:
        return {"active": False}

    controller_name = session.controller_name or session.user_id or "Unknown"
    return {
        "active": True,
        "user_id": session.user_id,
        "controller_name": controller_name,
        "session_id": session.session_id,
        "started_at": session.started_at_ms,
    }


def _now_ms() -> int:
    return int(time.time() * 1000)


def _build_message(
    msg_type: str,
    *,
    session_id: str | None = None,
    seq: int | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": msg_type,
        "session_id": session_id,
        "seq": seq,
        "ts": _now_ms(),
        "payload": payload or {},
    }


class RemoteDesktopWebSocketServer:
    def __init__(
        self,
        *,
        device_id: str,
        settings: RemoteDesktopSettings,
        jwt_secret: str,
        capture_engine: CaptureEngine,
        replay_guard: TokenReplayGuard | None = None,
        input_injector: InputInjector | None = None,
        keyboard_injector: KeyboardInjector | None = None,
        clipboard_manager: ClipboardManager | None = None,
        file_transfer_manager: TransferManager | None = None,
        transfer_transport: TransferTransport | None = None,
        display_enumerator: DisplayEnumerator | None = None,
        on_stream_started: Callable[[], None] | None = None,
        on_stream_stopped: Callable[[], None] | None = None,
    ) -> None:
        self._device_id = device_id
        self._settings = settings
        self._jwt_secret = jwt_secret
        self._capture_engine = capture_engine
        self._replay_guard = replay_guard or TokenReplayGuard()
        self._input_injector = input_injector or InputInjector()
        self._keyboard_injector = keyboard_injector or KeyboardInjector()
        self._clipboard_manager = clipboard_manager or ClipboardManager()
        ft_settings = settings.file_transfer
        self._transfer_transport = transfer_transport or Base64TransferTransport()
        self._file_transfer_manager = file_transfer_manager or TransferManager(
            workspace_dir=Path(ft_settings.workspace_dir),
            max_file_size_bytes=ft_settings.max_file_size_bytes,
            chunk_size_strategy=FixedChunkSizeStrategy(ft_settings.chunk_size),
            manifest_dir=Path(ft_settings.manifest_dir),
            partial_dir=Path(ft_settings.partial_dir),
            fsync_interval_bytes=ft_settings.fsync_interval_bytes,
            allow_overwrite=ft_settings.allow_overwrite,
            worker_pool=TransferWorkerPool(max_workers=ft_settings.worker_count),
        )
        self._on_stream_started = on_stream_started
        self._on_stream_stopped = on_stream_stopped
        self._display_enumerator = display_enumerator or default_display_enumerator()
        self._server: Server | None = None
        self._active_session: RemoteDesktopSession | None = None
        self._shutdown_event = asyncio.Event()
        self._bound_port: int | None = None

    @property
    def bound_port(self) -> int | None:
        return self._bound_port

    async def start(self) -> None:
        if self._server is not None:
            return

        self._shutdown_event.clear()
        self._server = await serve(
            self._connection_handler,
            self._settings.host,
            self._settings.port,
            process_request=self._process_request,
            subprotocols=[Subprotocol(self._settings.subprotocol)],
        )
        sockets = self._server.sockets
        if sockets:
            first_socket = next(iter(sockets))
            self._bound_port = first_socket.getsockname()[1]
        logger.info(
            "Remote desktop WebSocket server listening on %s:%s%s",
            self._settings.host,
            self._bound_port or self._settings.port,
            self._settings.path,
        )

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._active_session and self._active_session.is_active:
            self._active_session.mark_disconnected()
            self._active_session = None

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("Remote desktop WebSocket server stopped")

    def _process_request(
        self,
        connection: Any,
        request: Any,
    ) -> Any | None:
        path = request.path.split("?", 1)[0]
        if path != self._settings.path:
            return connection.respond(404, "Not Found")
        return None

    async def _connection_handler(self, websocket: Any) -> None:
        if self._shutdown_event.is_set():
            await websocket.close(1001, "Server shutting down")
            return

        if self._active_session and self._active_session.is_active:
            await self._emit_session_info(websocket, self._active_session)
            await self._send_error(
                websocket,
                code="SESSION_BUSY",
                message="Another remote desktop session is active",
            )
            await websocket.close(1008, "SESSION_BUSY")
            return

        session = RemoteDesktopSession(session_id=str(uuid4()))
        self._active_session = session

        try:
            session.mark_connecting()
            logger.info("Client connected")
            await self._run_session(websocket, session)
        except ConnectionClosed:
            pass
        except Exception:
            logger.error("Streaming error")
            await self._send_error(
                websocket,
                session_id=session.session_id,
                code="INTERNAL_ERROR",
                message="Internal server error",
            )
        finally:
            session.mark_disconnected()
            if self._active_session is session:
                self._active_session = None
            logger.info("Client disconnected")

    async def _run_session(self, websocket: Any, session: RemoteDesktopSession) -> None:
        last_pong_at = time.monotonic()
        outbound_seq = 0

        async def send_message(
            msg_type: str,
            payload: dict[str, Any] | None = None,
        ) -> None:
            nonlocal outbound_seq
            outbound_seq += 1
            message = _build_message(
                msg_type,
                session_id=session.session_id,
                seq=outbound_seq,
                payload=payload,
            )
            await websocket.send(json.dumps(message))

        async def heartbeat_loop() -> None:
            nonlocal last_pong_at
            while not self._shutdown_event.is_set():
                await asyncio.sleep(self._settings.ping_interval)
                if session.state != SessionState.ACTIVE:
                    continue

                if time.monotonic() - last_pong_at > self._settings.disconnect_timeout:
                    logger.warning(
                        "Remote desktop session timed out: %s",
                        session.session_id,
                    )
                    if session.started_at_ms is not None:
                        await send_message(
                            "SESSION_RELEASE",
                            payload={"session_id": session.session_id},
                        )
                    await send_message(
                        "ERROR",
                        payload={
                            "code": "TIMEOUT",
                            "message": "Session timed out",
                        },
                    )
                    await websocket.close(1008, "TIMEOUT")
                    return

                await send_message("PING", payload={})

        heartbeat_task = asyncio.create_task(heartbeat_loop())
        stream_runner = DesktopStreamRunner(
            capture_engine=self._capture_engine,
            settings=self._settings,
        )
        clipboard_poller = ClipboardPoller(
            self._clipboard_manager,
            poll_interval_ms=self._settings.clipboard_poll_interval_ms,
        )
        clipboard_watch_task = asyncio.create_task(
            clipboard_poller.run(
                send_changed=lambda text: send_message(
                    "CLIPBOARD_CHANGED",
                    payload={"text": text},
                ),
                should_poll=lambda: (
                    stream_runner.is_running
                    and clipboard_control_active
                    and has_permission(session.permissions, Permission.CLIPBOARD)
                ),
                shutdown_event=self._shutdown_event,
            )
        )
        mouse_control_active = False
        keyboard_control_active = False
        clipboard_control_active = False
        file_transfer_control_active = False
        active_upload_ids: set[str] = set()
        download_running: dict[str, bool] = {}
        session_authenticated = False
        monitor_manager = MonitorManager(
            enumerator=self._display_enumerator,
            capture_engine=self._capture_engine,
            input_injector=self._input_injector,
            immediate_capture=self._settings.monitor_switch_immediate_capture,
        )
        display_watcher = DisplayWatcher(
            manager=monitor_manager,
            streaming_interval_ms=self._settings.monitor_poll_interval_streaming_ms,
            idle_interval_ms=self._settings.monitor_poll_interval_idle_ms,
        )

        async def on_monitor_changed(change: Any, fallback: bool) -> None:
            await monitor_manager.emit_monitor_changed(
                send_message,
                change,
                fallback=fallback,
            )
            if stream_runner.is_running:
                await monitor_manager.send_monitor_list(send_message)

        monitor_watch_task = asyncio.create_task(
            display_watcher.run(
                on_changed=on_monitor_changed,
                should_poll=lambda: (
                    session_authenticated
                    and session.state == SessionState.ACTIVE
                    and display_watcher.mode != MonitorPollingMode.DISABLED
                ),
                shutdown_event=self._shutdown_event,
            )
        )

        try:
            async for raw_message in websocket:
                if self._shutdown_event.is_set():
                    break

                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError:
                    await self._send_error(
                        websocket,
                        session_id=session.session_id,
                        code="INVALID_MESSAGE",
                        message="Message must be valid JSON",
                    )
                    continue

                if not isinstance(message, dict):
                    await self._send_error(
                        websocket,
                        session_id=session.session_id,
                        code="INVALID_MESSAGE",
                        message="Message must be a JSON object",
                    )
                    continue

                msg_type = message.get("type")
                if not isinstance(msg_type, str):
                    await self._send_error(
                        websocket,
                        session_id=session.session_id,
                        code="INVALID_MESSAGE",
                        message="Missing message type",
                    )
                    continue

                if msg_type in NOT_IMPLEMENTED_TYPES:
                    await send_message(
                        "ERROR",
                        payload={
                            "code": "NOT_IMPLEMENTED",
                            "message": "Not implemented",
                        },
                    )
                    continue

                if msg_type == "HELLO":
                    await self._handle_hello(send_message, session)
                elif msg_type == "AUTH":
                    authenticated = await self._handle_auth(message, send_message, session)
                    if authenticated:
                        last_pong_at = time.monotonic()
                        session_authenticated = True
                        display_watcher.set_mode(MonitorPollingMode.IDLE)
                elif msg_type == "START_STREAM":
                    started = await self._handle_start_stream(
                        send_message,
                        session,
                        stream_runner,
                        monitor_manager,
                        display_watcher,
                    )
                    if started:
                        mouse_control_active = True
                        keyboard_control_active = True
                        clipboard_control_active = True
                        file_transfer_control_active = True
                elif msg_type == "STOP_STREAM":
                    stopped = await self._handle_stop_stream(
                        send_message,
                        session,
                        stream_runner,
                        display_watcher,
                    )
                    if stopped and mouse_control_active:
                        mouse_logger.info("Mouse control stopped")
                        mouse_control_active = False
                    if stopped and keyboard_control_active:
                        keyboard_control_active = False
                    if stopped and clipboard_control_active:
                        clipboard_control_active = False
                    if stopped and file_transfer_control_active:
                        file_transfer_control_active = False
                elif msg_type == "MOUSE_MOVE":
                    await self._handle_mouse_move(
                        message,
                        session,
                        stream_runner,
                        mouse_control_active,
                    )
                elif msg_type == "MOUSE_CLICK":
                    await self._handle_mouse_click(
                        message,
                        session,
                        stream_runner,
                        mouse_control_active,
                    )
                elif msg_type == "MOUSE_DOUBLE_CLICK":
                    await self._handle_mouse_double_click(
                        message,
                        session,
                        stream_runner,
                        mouse_control_active,
                    )
                elif msg_type == "MOUSE_SCROLL":
                    await self._handle_mouse_scroll(
                        message,
                        session,
                        stream_runner,
                        mouse_control_active,
                    )
                elif msg_type == "KEY_DOWN":
                    await self._handle_key_down(
                        message,
                        session,
                        stream_runner,
                        keyboard_control_active,
                    )
                elif msg_type == "KEY_UP":
                    await self._handle_key_up(
                        message,
                        session,
                        stream_runner,
                        keyboard_control_active,
                    )
                elif msg_type == "TEXT_INPUT":
                    await self._handle_text_input(
                        message,
                        session,
                        stream_runner,
                        keyboard_control_active,
                    )
                elif msg_type == "CLIPBOARD_GET":
                    await self._handle_clipboard_get(
                        send_message,
                        session,
                        stream_runner,
                        clipboard_control_active,
                    )
                elif msg_type == "CLIPBOARD_SET":
                    await self._handle_clipboard_set(
                        send_message,
                        message,
                        session,
                        stream_runner,
                        clipboard_control_active,
                        clipboard_poller,
                    )
                elif msg_type == "FILE_UPLOAD":
                    await self._handle_file_upload(
                        send_message,
                        message,
                        session,
                        stream_runner,
                        file_transfer_control_active,
                        active_upload_ids,
                    )
                elif msg_type == "FILE_DOWNLOAD":
                    await self._handle_file_download(
                        send_message,
                        message,
                        session,
                        stream_runner,
                        file_transfer_control_active,
                        download_running,
                    )
                elif msg_type == "MONITOR_SELECT":
                    await self._handle_monitor_select(
                        send_message,
                        message,
                        session,
                        stream_runner,
                        monitor_manager,
                    )
                elif msg_type == "SESSION_INFO":
                    await self._handle_session_info(send_message, session)
                elif msg_type == "SESSION_RELEASE":
                    await self._handle_session_release(websocket, session, send_message)
                    break
                elif msg_type == "FRAME":
                    await send_message(
                        "ERROR",
                        payload={
                            "code": "NOT_IMPLEMENTED",
                            "message": "Not implemented",
                        },
                    )
                elif msg_type == "PING":
                    await send_message("PONG", payload={})
                elif msg_type == "PONG":
                    last_pong_at = time.monotonic()
                elif msg_type == "ERROR":
                    payload = message.get("payload", {})
                    if isinstance(payload, dict):
                        logger.warning(
                            "Client reported error for session %s: %s",
                            session.session_id,
                            payload.get("message"),
                        )
                else:
                    await send_message(
                        "ERROR",
                        payload={
                            "code": "NOT_IMPLEMENTED",
                            "message": "Not implemented",
                        },
                    )
        finally:
            if session.started_at_ms is not None:
                try:
                    await send_message(
                        "SESSION_RELEASE",
                        payload={"session_id": session.session_id},
                    )
                except Exception:
                    pass
                session_logger.info("Session released: %s", session.session_id)
            if mouse_control_active:
                mouse_logger.info("Mouse control stopped")
            keyboard_control_active = False
            was_streaming = stream_runner.is_running
            await stream_runner.stop()
            if was_streaming and self._on_stream_stopped is not None:
                self._on_stream_stopped()
            display_watcher.set_mode(MonitorPollingMode.DISABLED)
            monitor_watch_task.cancel()
            heartbeat_task.cancel()
            clipboard_watch_task.cancel()
            for transfer_id in list(download_running.keys()):
                download_running[transfer_id] = False
                await self._file_transfer_manager.cancel_download(transfer_id)
            download_running.clear()
            for transfer_id in list(active_upload_ids):
                await self._file_transfer_manager.cancel_upload(transfer_id)
            active_upload_ids.clear()
            try:
                await monitor_watch_task
            except asyncio.CancelledError:
                pass
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            try:
                await clipboard_watch_task
            except asyncio.CancelledError:
                pass

    async def _handle_hello(
        self,
        send_message: Any,
        session: RemoteDesktopSession,
    ) -> None:
        if session.state not in {SessionState.CONNECTING, SessionState.ACTIVE}:
            await send_message(
                "ERROR",
                payload={
                    "code": "INVALID_STATE",
                    "message": "HELLO not allowed in current state",
                },
            )
            return

        await send_message(
            "HELLO",
            payload={
                "device_id": self._device_id,
                "session_id": session.session_id,
                "protocol": self._settings.subprotocol,
            },
        )

    async def _handle_auth(
        self,
        message: dict[str, Any],
        send_message: Any,
        session: RemoteDesktopSession,
    ) -> bool:
        if session.state != SessionState.CONNECTING:
            await send_message(
                "ERROR",
                payload={
                    "code": "INVALID_STATE",
                    "message": "AUTH not allowed in current state",
                },
            )
            return False

        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            await send_message(
                "ERROR",
                payload={
                    "code": "INVALID_MESSAGE",
                    "message": "AUTH payload must be an object",
                },
            )
            return False

        token = payload.get("token")
        if not isinstance(token, str) or not token:
            await send_message(
                "ERROR",
                payload={
                    "code": "AUTH_FAILED",
                    "message": "Missing session token",
                },
            )
            return False

        try:
            claims = validate_session_token(
                token,
                device_id=self._device_id,
                secret=self._jwt_secret,
                algorithm=self._settings.jwt_algorithm,
                replay_guard=self._replay_guard,
            )
        except TokenValidationError as exc:
            if exc.reason == "expired":
                error_code = "TOKEN_EXPIRED"
            elif exc.reason == "reused":
                error_code = "TOKEN_REUSED"
            else:
                error_code = "AUTH_FAILED"
            await send_message(
                "ERROR",
                payload={
                    "code": error_code,
                    "message": "Invalid session token",
                },
            )
            return False

        session.bind_remote_session_id(claims.session_id)
        session.set_permissions(claims.permissions)
        session.bind_controller(claims.user_id, claims.controller_name)
        session.start_controller_session(_now_ms())
        session.mark_authenticated()
        session.mark_active()
        session_logger.info(
            "Controller session started: user=%s session=%s",
            session.user_id,
            session.session_id,
        )
        await send_message(
            "AUTH",
            payload={
                "authenticated": True,
                "session_id": claims.session_id,
            },
        )
        await send_message("SESSION_INFO", payload=_session_info_payload(session))
        return True

    async def _handle_start_stream(
        self,
        send_message: Any,
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        monitor_manager: MonitorManager,
        display_watcher: DisplayWatcher,
    ) -> bool:
        if session.state != SessionState.ACTIVE:
            await send_message(
                "ERROR",
                payload={
                    "code": "INVALID_STATE",
                    "message": "START_STREAM not allowed in current state",
                },
            )
            return False

        if not has_permission(session.permissions, Permission.DESKTOP):
            await send_message(
                "ERROR",
                payload={
                    "code": "PERMISSION_DENIED",
                    "message": "Desktop permission required",
                },
            )
            return False

        if stream_runner.is_running:
            await send_message(
                "START_STREAM",
                payload={"streaming": True},
            )
            await monitor_manager.send_monitor_list(send_message)
            return False

        if self._on_stream_started is not None:
            self._on_stream_started()

        monitor_manager.bind_stream_runner(stream_runner)
        await monitor_manager.initialize()
        display_watcher.set_mode(MonitorPollingMode.STREAMING)

        await stream_runner.start(send_message)
        logger.info("Stream started")
        mouse_logger.info("Mouse control started")
        await send_message(
            "START_STREAM",
            payload={"streaming": True},
        )
        await monitor_manager.send_monitor_list(send_message)
        return True

    async def _handle_stop_stream(
        self,
        send_message: Any,
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        display_watcher: DisplayWatcher,
    ) -> bool:
        if session.state != SessionState.ACTIVE:
            await send_message(
                "ERROR",
                payload={
                    "code": "INVALID_STATE",
                    "message": "STOP_STREAM not allowed in current state",
                },
            )
            return False

        was_streaming = stream_runner.is_running
        await stream_runner.stop()
        if was_streaming and self._on_stream_stopped is not None:
            self._on_stream_stopped()
        display_watcher.set_mode(MonitorPollingMode.IDLE)

        logger.info("Stream stopped")
        await send_message(
            "STOP_STREAM",
            payload={"streaming": False},
        )
        return was_streaming

    async def _handle_monitor_select(
        self,
        send_message: Any,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        monitor_manager: MonitorManager,
    ) -> None:
        if session.state != SessionState.ACTIVE:
            return
        if not has_permission(session.permissions, Permission.DESKTOP):
            return

        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            monitor_logger.info("Invalid monitor select event")
            return

        monitor_id = payload.get("monitor_id")
        if not isinstance(monitor_id, str) or not monitor_id:
            return

        try:
            await monitor_manager.select_monitor(monitor_id, send_message)
        except MonitorError as exc:
            monitor_logger.info("Monitor select failed: %s", exc.code)
            await send_message(
                "MONITOR_SELECT",
                {
                    "monitor_id": monitor_id,
                    "accepted": False,
                    "code": exc.code,
                    "message": exc.message,
                },
            )

    async def _handle_mouse_move(
        self,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        mouse_control_active: bool,
    ) -> None:
        if not self._mouse_input_allowed(session, stream_runner, mouse_control_active):
            return

        fields = extract_mouse_fields(message)
        x = parse_normalized_coordinate_strict(fields.get("x"))
        y = parse_normalized_coordinate_strict(fields.get("y"))
        if x is None or y is None:
            mouse_logger.info("Invalid mouse event")
            return

        await asyncio.to_thread(self._input_injector.move, x, y)

    async def _handle_mouse_click(
        self,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        mouse_control_active: bool,
    ) -> None:
        if not self._mouse_input_allowed(session, stream_runner, mouse_control_active):
            return

        fields = extract_mouse_fields(message)
        button = fields.get("button")
        if button not in {"left", "right"}:
            mouse_logger.info("Invalid mouse event")
            return

        await asyncio.to_thread(self._input_injector.click, button)

    async def _handle_mouse_double_click(
        self,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        mouse_control_active: bool,
    ) -> None:
        if not self._mouse_input_allowed(session, stream_runner, mouse_control_active):
            return

        await asyncio.to_thread(self._input_injector.double_click)

    async def _handle_mouse_scroll(
        self,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        mouse_control_active: bool,
    ) -> None:
        if not self._mouse_input_allowed(session, stream_runner, mouse_control_active):
            return

        fields = extract_mouse_fields(message)
        delta = parse_scroll_delta(fields.get("delta"))
        if delta is None:
            mouse_logger.info("Invalid mouse event")
            return

        await asyncio.to_thread(self._input_injector.scroll, delta)

    def _mouse_input_allowed(
        self,
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        mouse_control_active: bool,
    ) -> bool:
        if session.state != SessionState.ACTIVE:
            mouse_logger.info("Invalid mouse event")
            return False
        if not stream_runner.is_running or not mouse_control_active:
            return False
        if not has_permission(session.permissions, Permission.MOUSE):
            return False
        return True

    async def _handle_key_down(
        self,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        keyboard_control_active: bool,
    ) -> None:
        if not stream_runner.is_running or not keyboard_control_active:
            return
        if not has_permission(session.permissions, Permission.KEYBOARD):
            return

        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            keyboard_logger.info("Invalid keyboard event")
            return

        key = parse_key(payload.get("key"))
        if key is None:
            keyboard_logger.info("Invalid keyboard event")
            return

        try:
            await asyncio.to_thread(self._keyboard_injector.key_down, key)
        except Exception:
            keyboard_logger.info("Invalid keyboard event")

    async def _handle_key_up(
        self,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        keyboard_control_active: bool,
    ) -> None:
        if not stream_runner.is_running or not keyboard_control_active:
            return
        if not has_permission(session.permissions, Permission.KEYBOARD):
            return

        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            keyboard_logger.info("Invalid keyboard event")
            return

        key = parse_key(payload.get("key"))
        if key is None:
            keyboard_logger.info("Invalid keyboard event")
            return

        try:
            await asyncio.to_thread(self._keyboard_injector.key_up, key)
        except Exception:
            keyboard_logger.info("Invalid keyboard event")

    async def _handle_text_input(
        self,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        keyboard_control_active: bool,
    ) -> None:
        if not stream_runner.is_running or not keyboard_control_active:
            return
        if not has_permission(session.permissions, Permission.KEYBOARD):
            return

        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            keyboard_logger.info("Invalid keyboard event")
            return

        text = parse_text_input(payload.get("text"))
        if text is None:
            keyboard_logger.info("Invalid keyboard event")
            return

        try:
            await asyncio.to_thread(self._keyboard_injector.text_input, text)
        except Exception:
            keyboard_logger.info("Invalid keyboard event")

    async def _handle_clipboard_get(
        self,
        send_message: Any,
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        clipboard_control_active: bool,
    ) -> None:
        if not stream_runner.is_running or not clipboard_control_active:
            return
        if not has_permission(session.permissions, Permission.CLIPBOARD):
            return

        try:
            text = await asyncio.to_thread(self._clipboard_manager.read)
        except Exception:
            clipboard_logger.info("Invalid clipboard event")
            return

        await send_message("CLIPBOARD_GET", payload={"text": text})

    async def _handle_clipboard_set(
        self,
        send_message: Any,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        clipboard_control_active: bool,
        clipboard_poller: ClipboardPoller,
    ) -> None:
        if not stream_runner.is_running or not clipboard_control_active:
            return
        if not has_permission(session.permissions, Permission.CLIPBOARD):
            return

        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            clipboard_logger.info("Invalid clipboard event")
            return

        text = parse_clipboard_text(payload.get("text"))
        if text is None:
            clipboard_logger.info("Invalid clipboard event")
            return

        try:
            await asyncio.to_thread(self._clipboard_manager.write, text)
        except Exception:
            clipboard_logger.info("Invalid clipboard event")
            return

        clipboard_poller.note_text(text)
        try:
            await send_message("CLIPBOARD_CHANGED", payload={"text": text})
        except Exception:
            clipboard_logger.info("Clipboard changed broadcast failed")

    async def _send_file_error(
        self,
        send_message: Any,
        transfer_id: str | None,
        code: str,
        message: str,
    ) -> None:
        await send_message(
            "FILE_ERROR",
            payload={
                "transfer_id": transfer_id,
                "code": code,
                "message": message,
            },
        )

    async def _send_file_progress(
        self,
        send_message: Any,
        transfer_id: str,
        transferred: int,
        total: int,
        direction: str,
        *,
        state: str = "active",
    ) -> None:
        await send_message(
            "FILE_PROGRESS",
            payload={
                "transfer_id": transfer_id,
                "transferred": transferred,
                "total": total,
                "direction": direction,
                "state": state,
            },
        )

    async def _handle_file_upload(
        self,
        send_message: Any,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        file_transfer_control_active: bool,
        active_upload_ids: set[str],
    ) -> None:
        if not stream_runner.is_running or not file_transfer_control_active:
            return
        if not has_permission(session.permissions, Permission.FILE_TRANSFER):
            return

        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            file_logger.info("Invalid file transfer event")
            return

        transfer_id = payload.get("transfer_id")
        if not isinstance(transfer_id, str) or not transfer_id:
            return

        manager = self._file_transfer_manager
        transport = self._transfer_transport

        if payload.get("cancel") is True:
            active_upload_ids.discard(transfer_id)
            await manager.cancel_upload(transfer_id)
            await self._send_file_error(
                send_message,
                transfer_id,
                "CANCELLED",
                "Transfer cancelled",
            )
            return

        if payload.get("pause") is True and "path" not in payload and "chunk" not in payload:
            try:
                await manager.pause_upload(transfer_id)
                session_upload = manager.get_upload(transfer_id)
                if session_upload is not None:
                    await self._send_file_progress(
                        send_message,
                        transfer_id,
                        session_upload.transferred,
                        session_upload.total_size,
                        "upload",
                        state="paused",
                    )
            except FileTransferError as exc:
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    exc.code,
                    exc.message,
                )
            return

        if payload.get("resume") is True and "path" not in payload and "chunk" not in payload:
            try:
                session_upload = await manager.resume_upload(transfer_id)
                active_upload_ids.add(transfer_id)
                await self._send_file_progress(
                    send_message,
                    transfer_id,
                    session_upload.transferred,
                    session_upload.total_size,
                    "upload",
                    state="active",
                )
            except FileTransferError as exc:
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    exc.code,
                    exc.message,
                )
            return

        if "chunk" in payload:
            data = transport.decode_chunk(payload.get("chunk"))
            if data is None:
                active_upload_ids.discard(transfer_id)
                await manager.cancel_upload(transfer_id)
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    "INVALID_CHUNK",
                    "Invalid chunk data",
                )
                return

            offset = payload.get("offset")
            parsed_offset = offset if isinstance(offset, int) and not isinstance(offset, bool) else None

            try:
                transferred, total, complete = await manager.handle_upload_chunk(
                    transfer_id,
                    data,
                    offset=parsed_offset,
                )
            except FileTransferError as exc:
                active_upload_ids.discard(transfer_id)
                if exc.code != "PAUSED":
                    await manager.cancel_upload(transfer_id)
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    exc.code,
                    exc.message,
                )
                return

            await self._send_file_progress(
                send_message,
                transfer_id,
                transferred,
                total,
                "upload",
            )

            if not complete:
                return

            active_upload_ids.discard(transfer_id)
            try:
                path, size, digest = await manager.finalize_upload(transfer_id)
            except FileTransferError as exc:
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    exc.code,
                    exc.message,
                )
                return

            complete_payload: dict[str, Any] = {
                "transfer_id": transfer_id,
                "path": path,
                "size": size,
            }
            if digest is not None:
                complete_payload["sha256"] = digest
            await send_message("FILE_COMPLETE", payload=complete_payload)
            return

        path = payload.get("path")
        size = payload.get("size")
        if not isinstance(path, str) or size is None:
            return

        if not isinstance(size, int) or isinstance(size, bool):
            return

        resume = payload.get("resume") is True
        overwrite = payload.get("overwrite") is True
        offset = payload.get("offset")
        parsed_offset = offset if isinstance(offset, int) and not isinstance(offset, bool) else 0
        sha256 = parse_sha256(payload.get("sha256"))

        try:
            session_upload = await manager.initiate_upload(
                transfer_id=transfer_id,
                relative_path=path,
                total_size=size,
                sha256=sha256,
                offset=parsed_offset,
                resume=resume,
                overwrite=overwrite,
            )
        except FileTransferError as exc:
            await self._send_file_error(
                send_message,
                transfer_id,
                exc.code,
                exc.message,
            )
            return

        active_upload_ids.add(transfer_id)
        await self._send_file_progress(
            send_message,
            transfer_id,
            session_upload.transferred,
            session_upload.total_size,
            "upload",
            state="queued" if resume else "active",
        )

    async def _handle_file_download(
        self,
        send_message: Any,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        file_transfer_control_active: bool,
        download_running: dict[str, bool],
    ) -> None:
        if not stream_runner.is_running or not file_transfer_control_active:
            return
        if not has_permission(session.permissions, Permission.FILE_TRANSFER):
            return

        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            file_logger.info("Invalid file transfer event")
            return

        transfer_id = payload.get("transfer_id")
        if not isinstance(transfer_id, str) or not transfer_id:
            return

        manager = self._file_transfer_manager
        transport = self._transfer_transport

        if payload.get("cancel") is True:
            download_running[transfer_id] = False
            await manager.cancel_download(transfer_id)
            download_running.pop(transfer_id, None)
            await self._send_file_error(
                send_message,
                transfer_id,
                "CANCELLED",
                "Transfer cancelled",
            )
            return

        if payload.get("pause") is True and "path" not in payload:
            try:
                await manager.pause_download(transfer_id)
                session_download = manager.get_download(transfer_id)
                if session_download is not None:
                    await self._send_file_progress(
                        send_message,
                        transfer_id,
                        session_download.offset,
                        session_download.total_size,
                        "download",
                        state="paused",
                    )
            except FileTransferError as exc:
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    exc.code,
                    exc.message,
                )
            return

        if payload.get("resume") is True and "path" not in payload:
            try:
                await manager.resume_download(transfer_id)
                session_download = manager.get_download(transfer_id)
                if session_download is not None:
                    await self._send_file_progress(
                        send_message,
                        transfer_id,
                        session_download.offset,
                        session_download.total_size,
                        "download",
                        state="active",
                    )
            except FileTransferError as exc:
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    exc.code,
                    exc.message,
                )
            return

        path = payload.get("path")
        if not isinstance(path, str):
            return

        resume = payload.get("resume") is True
        offset = payload.get("offset")
        parsed_offset = offset if isinstance(offset, int) and not isinstance(offset, bool) else 0

        try:
            session_download = await manager.initiate_download(
                transfer_id=transfer_id,
                relative_path=path,
                offset=parsed_offset,
                resume=resume,
            )
        except FileTransferError as exc:
            await self._send_file_error(
                send_message,
                transfer_id,
                exc.code,
                exc.message,
            )
            return

        download_running[transfer_id] = True

        async def on_chunk(
            chunk_transfer_id: str,
            chunk: bytes,
            chunk_offset: int,
            final: bool,
        ) -> None:
            await send_message(
                "FILE_DOWNLOAD",
                payload={
                    "transfer_id": chunk_transfer_id,
                    "chunk": transport.encode_chunk(chunk),
                    "offset": chunk_offset,
                    "final": final,
                },
            )

        async def on_progress(
            progress_transfer_id: str,
            transferred: int,
            total: int,
            direction: str,
        ) -> None:
            await self._send_file_progress(
                send_message,
                progress_transfer_id,
                transferred,
                total,
                direction,
            )

        async def on_complete(
            complete_transfer_id: str,
            relative_path: str,
            total: int,
            digest: str | None,
        ) -> None:
            download_running.pop(complete_transfer_id, None)
            complete_payload: dict[str, Any] = {
                "transfer_id": complete_transfer_id,
                "path": relative_path,
                "size": total,
            }
            if digest is not None:
                complete_payload["sha256"] = digest
            await send_message("FILE_COMPLETE", payload=complete_payload)

        async def on_error(
            error_transfer_id: str,
            code: str,
            error_message: str,
        ) -> None:
            download_running.pop(error_transfer_id, None)
            await self._send_file_error(
                send_message,
                error_transfer_id,
                code,
                error_message,
            )

        await manager.queue_download(
            session_download,
            on_chunk=on_chunk,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
            should_continue=lambda: download_running.get(transfer_id, False),
        )

        await self._send_file_progress(
            send_message,
            transfer_id,
            session_download.offset,
            session_download.total_size,
            "download",
            state="queued",
        )

    async def _emit_session_info(
        self,
        websocket: Any,
        session: RemoteDesktopSession | None,
    ) -> None:
        message = _build_message("SESSION_INFO", payload=_session_info_payload(session))
        try:
            await websocket.send(json.dumps(message))
        except ConnectionClosed:
            pass

    async def _handle_session_info(
        self,
        send_message: Any,
        session: RemoteDesktopSession,
    ) -> None:
        await send_message("SESSION_INFO", payload=_session_info_payload(session))

    async def _handle_session_release(
        self,
        websocket: Any,
        session: RemoteDesktopSession,
        send_message: Any,
    ) -> None:
        if session.state != SessionState.ACTIVE:
            return

        await send_message(
            "SESSION_RELEASE",
            payload={"session_id": session.session_id},
        )
        session_logger.info("Session released by client: %s", session.session_id)
        await websocket.close(1000, "SESSION_RELEASE")

    async def _send_error(
        self,
        websocket: Any,
        *,
        code: str,
        message: str,
        session_id: str | None = None,
    ) -> None:
        payload = _build_message(
            "ERROR",
            session_id=session_id,
            payload={"code": code, "message": message},
        )
        try:
            await websocket.send(json.dumps(payload))
        except ConnectionClosed:
            pass
