from __future__ import annotations

import asyncio
import time
from io import BytesIO
from typing import Any
from unittest.mock import Mock

import pytest
from PIL import Image
from websockets.asyncio.client import connect

from ottomandevice.remote_desktop.auth import create_session_jwt
from ottomandevice.remote_desktop.websocket_server import RemoteDesktopWebSocketServer
from tests.unit.test_remote_desktop import (
    TEST_DEVICE_ID,
    TEST_JWT_SECRET,
    _recv_json,
    _send_json,
    _test_remote_desktop_settings,
)

_JPEG_BYTES: bytes | None = None


def _minimal_jpeg_bytes() -> bytes:
    global _JPEG_BYTES
    if _JPEG_BYTES is None:
        buffer = BytesIO()
        Image.new("RGB", (128, 72), color=(10, 20, 30)).save(
            buffer,
            format="JPEG",
            quality=70,
        )
        _JPEG_BYTES = buffer.getvalue()
    return _JPEG_BYTES


class MockCaptureEngine:
    def __init__(self) -> None:
        self._sequence = 0

    def capture_and_encode(self) -> tuple[bytes, int, int]:
        self._sequence += 1
        return _minimal_jpeg_bytes(), 128, 72


async def _start_server(
    *,
    on_stream_started: Mock | None = None,
    on_stream_stopped: Mock | None = None,
) -> RemoteDesktopWebSocketServer:
    server = RemoteDesktopWebSocketServer(
        device_id=TEST_DEVICE_ID,
        settings=_test_remote_desktop_settings(),
        jwt_secret=TEST_JWT_SECRET,
        capture_engine=MockCaptureEngine(),
        on_stream_started=on_stream_started,
        on_stream_stopped=on_stream_stopped,
    )
    await server.start()
    return server


def _ws_uri(server: RemoteDesktopWebSocketServer) -> str:
    port = server.bound_port
    assert port is not None
    settings = _test_remote_desktop_settings()
    return f"ws://127.0.0.1:{port}{settings.path}"


async def _authenticate(websocket: Any) -> None:
    token = create_session_jwt(
        device_id=TEST_DEVICE_ID,
        secret=TEST_JWT_SECRET,
        ttl_seconds=60,
        permissions=["desktop"],
    )
    await _send_json(websocket, "HELLO")
    hello = await _recv_json(websocket)
    assert hello["type"] == "HELLO"

    await _send_json(websocket, "AUTH", {"token": token})
    auth = await _recv_json(websocket)
    assert auth["type"] == "AUTH"
    assert auth["payload"]["authenticated"] is True


async def _recv_type(
    websocket: Any,
    msg_type: str,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        message = await _recv_json(websocket, timeout=remaining)
        if message["type"] == "PING":
            await _send_json(websocket, "PONG")
            continue
        if message["type"] == msg_type:
            return message
    raise TimeoutError(f"Timed out waiting for {msg_type}")


async def _recv_no_type(
    websocket: Any,
    msg_type: str,
    *,
    timeout: float = 0.6,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.05, deadline - time.monotonic())
        try:
            message = await _recv_json(websocket, timeout=remaining)
        except TimeoutError:
            return
        if message["type"] == "PING":
            await _send_json(websocket, "PONG")
            continue
        if message["type"] == msg_type:
            raise AssertionError(f"Unexpected {msg_type} message: {message}")
    return


@pytest.mark.asyncio
async def test_start_stream_receives_frames() -> None:
    server = await _start_server()
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "START_STREAM")
            started = await _recv_type(websocket, "START_STREAM")
            assert started["payload"]["streaming"] is True

            frame_one = await _recv_type(websocket, "FRAME", timeout=3.0)
            frame_two = await _recv_type(websocket, "FRAME", timeout=3.0)
            assert frame_one["payload"]["sequence"] == 1
            assert frame_two["payload"]["sequence"] == 2
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_stop_stream_stops_frames() -> None:
    server = await _start_server()
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "START_STREAM")
            await _recv_type(websocket, "START_STREAM")
            await _recv_type(websocket, "FRAME", timeout=3.0)

            await _send_json(websocket, "STOP_STREAM")
            stopped = await _recv_type(websocket, "STOP_STREAM")
            assert stopped["payload"]["streaming"] is False

            await _recv_no_type(websocket, "FRAME", timeout=0.6)
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_frame_sequence_increments() -> None:
    server = await _start_server()
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "START_STREAM")
            await _recv_type(websocket, "START_STREAM")

            sequences: list[int] = []
            for _ in range(4):
                frame = await _recv_type(websocket, "FRAME", timeout=3.0)
                sequences.append(frame["payload"]["sequence"])

            assert sequences == sorted(sequences)
            assert len(set(sequences)) == len(sequences)
            assert sequences[-1] - sequences[0] == len(sequences) - 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_reconnect_and_restart_stream() -> None:
    server = await _start_server()
    try:
        uri = _ws_uri(server)
        settings = _test_remote_desktop_settings()

        async with connect(uri, subprotocols=[settings.subprotocol]) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "START_STREAM")
            await _recv_type(websocket, "START_STREAM")
            await _recv_type(websocket, "FRAME", timeout=3.0)

        async with connect(uri, subprotocols=[settings.subprotocol]) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "START_STREAM")
            started = await _recv_type(websocket, "START_STREAM")
            assert started["payload"]["streaming"] is True
            frame = await _recv_type(websocket, "FRAME", timeout=3.0)
            assert frame["payload"]["sequence"] == 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_graceful_shutdown_during_stream() -> None:
    server = await _start_server()
    uri = _ws_uri(server)
    settings = _test_remote_desktop_settings()

    async with connect(uri, subprotocols=[settings.subprotocol]) as websocket:
        await _authenticate(websocket)
        await _send_json(websocket, "START_STREAM")
        await _recv_type(websocket, "START_STREAM")
        await _recv_type(websocket, "FRAME", timeout=3.0)

        await server.stop()

        with pytest.raises(Exception):
            await asyncio.wait_for(websocket.recv(), timeout=3.0)


@pytest.mark.asyncio
async def test_start_stream_pauses_storage_callback() -> None:
    on_stream_started = Mock()
    server = await _start_server(on_stream_started=on_stream_started)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "START_STREAM")
            await _recv_type(websocket, "START_STREAM")
            on_stream_started.assert_called_once()
    finally:
        await server.stop()

@pytest.mark.asyncio
async def test_fallback_to_storage_after_stop_stream() -> None:
    on_stream_stopped = Mock()
    server = await _start_server(on_stream_stopped=on_stream_stopped)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "START_STREAM")
            await _recv_type(websocket, "START_STREAM")
            await _recv_type(websocket, "FRAME", timeout=3.0)

            await _send_json(websocket, "STOP_STREAM")
            await _recv_type(websocket, "STOP_STREAM")
            on_stream_stopped.assert_called_once()
    finally:
        await server.stop()

