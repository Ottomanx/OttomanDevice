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
    parse_clipboard_text,
)
from ottomandevice.remote_desktop.file_transfer import (
    DownloadTransfer,
    FileTransferError,
    FileTransferManager,
    UploadTransfer,
    parse_chunk_data,
    parse_transfer_size,
    validate_relative_path,
)
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
        file_transfer_manager: FileTransferManager | None = None,
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
        self._file_transfer_manager = file_transfer_manager or FileTransferManager(
            workspace_dir=Path(ft_settings.workspace_dir),
            max_file_size_bytes=ft_settings.max_file_size_bytes,
            chunk_size=ft_settings.chunk_size,
        )
        self._on_stream_started = on_stream_started
        self._on_stream_stopped = on_stream_stopped
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
        clipboard_watch_task = asyncio.create_task(
            self._clipboard_watch_loop(
                send_message=send_message,
                session=session,
                stream_runner=stream_runner,
            )
        )
        mouse_control_active = False
        keyboard_control_active = False
        clipboard_control_active = False
        file_transfer_control_active = False
        active_uploads: dict[str, UploadTransfer] = {}
        active_downloads: dict[str, DownloadTransfer] = {}
        download_tasks: dict[str, asyncio.Task[Any]] = {}

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
                elif msg_type == "START_STREAM":
                    started = await self._handle_start_stream(
                        send_message,
                        session,
                        stream_runner,
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
                    )
                elif msg_type == "FILE_UPLOAD":
                    await self._handle_file_upload(
                        send_message,
                        message,
                        session,
                        stream_runner,
                        file_transfer_control_active,
                        active_uploads,
                    )
                elif msg_type == "FILE_DOWNLOAD":
                    await self._handle_file_download(
                        send_message,
                        message,
                        session,
                        stream_runner,
                        file_transfer_control_active,
                        active_downloads,
                        download_tasks,
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
            heartbeat_task.cancel()
            clipboard_watch_task.cancel()
            for task in download_tasks.values():
                task.cancel()
            for transfer in active_downloads.values():
                transfer.cancelled = True
            active_uploads.clear()
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

        if stream_runner.is_running:
            await send_message(
                "START_STREAM",
                payload={"streaming": True},
            )
            return False

        if self._on_stream_started is not None:
            self._on_stream_started()

        await stream_runner.start(send_message)
        logger.info("Stream started")
        mouse_logger.info("Mouse control started")
        await send_message(
            "START_STREAM",
            payload={"streaming": True},
        )
        return True

    async def _handle_stop_stream(
        self,
        send_message: Any,
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
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

        logger.info("Stream stopped")
        await send_message(
            "STOP_STREAM",
            payload={"streaming": False},
        )
        return was_streaming

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

    async def _clipboard_watch_loop(
        self,
        *,
        send_message: Any,
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
    ) -> None:
        last_text: str | None = None
        while not self._shutdown_event.is_set():
            await asyncio.sleep(1.0)
            if not stream_runner.is_running:
                last_text = None
                continue
            if not has_permission(session.permissions, Permission.CLIPBOARD):
                continue

            try:
                text = await asyncio.to_thread(self._clipboard_manager.read)
            except Exception:
                clipboard_logger.info("Clipboard read failed")
                continue

            if text != last_text:
                last_text = text
                await send_message("CLIPBOARD_CHANGED", payload={"text": text})

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

        await send_message("CLIPBOARD_CHANGED", payload={"text": text})

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
    ) -> None:
        await send_message(
            "FILE_PROGRESS",
            payload={
                "transfer_id": transfer_id,
                "transferred": transferred,
                "total": total,
                "direction": direction,
            },
        )

    async def _handle_file_upload(
        self,
        send_message: Any,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        file_transfer_control_active: bool,
        active_uploads: dict[str, UploadTransfer],
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

        if payload.get("cancel") is True:
            upload = active_uploads.pop(transfer_id, None)
            if upload is not None:
                upload.cancelled = True
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    "CANCELLED",
                    "Transfer cancelled",
                )
            return

        if "chunk" in payload:
            upload = active_uploads.get(transfer_id)
            if upload is None or upload.cancelled:
                return

            data = parse_chunk_data(payload.get("chunk"))
            if data is None:
                active_uploads.pop(transfer_id, None)
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    "INVALID_CHUNK",
                    "Invalid chunk data",
                )
                return

            if len(upload.buffer) + len(data) > upload.total_size:
                active_uploads.pop(transfer_id, None)
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    "FILE_TOO_LARGE",
                    "Upload exceeds declared size",
                )
                return

            upload.buffer.extend(data)
            transferred = len(upload.buffer)
            await self._send_file_progress(
                send_message,
                transfer_id,
                transferred,
                upload.total_size,
                "upload",
            )

            if transferred < upload.total_size:
                return

            active_uploads.pop(transfer_id, None)
            try:
                await asyncio.to_thread(
                    self._file_transfer_manager.write_file,
                    upload.target_path,
                    bytes(upload.buffer),
                )
            except FileTransferError as exc:
                await self._send_file_error(
                    send_message,
                    transfer_id,
                    exc.code,
                    exc.message,
                )
                return

            await send_message(
                "FILE_COMPLETE",
                payload={
                    "transfer_id": transfer_id,
                    "path": upload.relative_path,
                    "size": upload.total_size,
                },
            )
            return

        path = payload.get("path")
        size = payload.get("size")
        if not isinstance(path, str) or size is None:
            return

        relative_path = validate_relative_path(path)
        if relative_path is None:
            await self._send_file_error(
                send_message,
                transfer_id,
                "INVALID_PATH",
                "Invalid file path",
            )
            return

        parsed_size = parse_transfer_size(
            size,
            max_size=self._file_transfer_manager.max_file_size_bytes,
        )
        if parsed_size is None:
            await self._send_file_error(
                send_message,
                transfer_id,
                "FILE_TOO_LARGE",
                "Invalid file size",
            )
            return

        target = self._file_transfer_manager.resolve_path(relative_path)
        if target is None:
            await self._send_file_error(
                send_message,
                transfer_id,
                "INVALID_PATH",
                "Invalid file path",
            )
            return

        if transfer_id in active_uploads:
            await self._send_file_error(
                send_message,
                transfer_id,
                "INVALID_TRANSFER",
                "Transfer already active",
            )
            return

        active_uploads[transfer_id] = UploadTransfer(
            transfer_id=transfer_id,
            relative_path=relative_path,
            target_path=target,
            total_size=parsed_size,
        )
        await self._send_file_progress(
            send_message,
            transfer_id,
            0,
            parsed_size,
            "upload",
        )

    async def _run_file_download(
        self,
        send_message: Any,
        transfer: DownloadTransfer,
        active_downloads: dict[str, DownloadTransfer],
    ) -> None:
        transfer_id = transfer.transfer_id
        try:
            data = await asyncio.to_thread(
                self._file_transfer_manager.read_file,
                transfer.source_path,
            )
            if transfer.cancelled:
                raise FileTransferError("CANCELLED", "Transfer cancelled")

            chunk_size = self._file_transfer_manager.chunk_size
            total = len(data)
            offset = 0
            while offset < total:
                if transfer.cancelled:
                    raise FileTransferError("CANCELLED", "Transfer cancelled")

                end = min(offset + chunk_size, total)
                chunk = data[offset:end]
                final = end >= total
                await send_message(
                    "FILE_DOWNLOAD",
                    payload={
                        "transfer_id": transfer_id,
                        "chunk": self._file_transfer_manager.encode_chunk(chunk),
                        "offset": offset,
                        "final": final,
                    },
                )
                offset = end
                await self._send_file_progress(
                    send_message,
                    transfer_id,
                    offset,
                    total,
                    "download",
                )

            await send_message(
                "FILE_COMPLETE",
                payload={
                    "transfer_id": transfer_id,
                    "path": transfer.relative_path,
                    "size": total,
                },
            )
        except FileTransferError as exc:
            await self._send_file_error(
                send_message,
                transfer_id,
                exc.code,
                exc.message,
            )
        except Exception:
            file_logger.info("File download failed")
            await self._send_file_error(
                send_message,
                transfer_id,
                "INTERNAL_ERROR",
                "Download failed",
            )
        finally:
            active_downloads.pop(transfer_id, None)

    async def _handle_file_download(
        self,
        send_message: Any,
        message: dict[str, Any],
        session: RemoteDesktopSession,
        stream_runner: DesktopStreamRunner,
        file_transfer_control_active: bool,
        active_downloads: dict[str, DownloadTransfer],
        download_tasks: dict[str, asyncio.Task[Any]],
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

        if payload.get("cancel") is True:
            transfer = active_downloads.get(transfer_id)
            if transfer is not None:
                transfer.cancelled = True
            task = download_tasks.pop(transfer_id, None)
            if task is not None:
                task.cancel()
            active_downloads.pop(transfer_id, None)
            await self._send_file_error(
                send_message,
                transfer_id,
                "CANCELLED",
                "Transfer cancelled",
            )
            return

        path = payload.get("path")
        if not isinstance(path, str):
            return

        relative_path = validate_relative_path(path)
        if relative_path is None:
            await self._send_file_error(
                send_message,
                transfer_id,
                "INVALID_PATH",
                "Invalid file path",
            )
            return

        target = self._file_transfer_manager.resolve_path(relative_path)
        if target is None:
            await self._send_file_error(
                send_message,
                transfer_id,
                "INVALID_PATH",
                "Invalid file path",
            )
            return

        if transfer_id in active_downloads:
            await self._send_file_error(
                send_message,
                transfer_id,
                "INVALID_TRANSFER",
                "Transfer already active",
            )
            return

        if not target.is_file():
            await self._send_file_error(
                send_message,
                transfer_id,
                "NOT_FOUND",
                "File not found",
            )
            return

        try:
            size = target.stat().st_size
        except OSError:
            await self._send_file_error(
                send_message,
                transfer_id,
                "NOT_FOUND",
                "File not found",
            )
            return

        if size > self._file_transfer_manager.max_file_size_bytes:
            await self._send_file_error(
                send_message,
                transfer_id,
                "FILE_TOO_LARGE",
                "File exceeds maximum size",
            )
            return

        transfer = DownloadTransfer(
            transfer_id=transfer_id,
            relative_path=relative_path,
            source_path=target,
            total_size=size,
        )
        active_downloads[transfer_id] = transfer
        download_tasks[transfer_id] = asyncio.create_task(
            self._run_file_download(send_message, transfer, active_downloads)
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
