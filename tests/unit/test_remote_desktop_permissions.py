from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Any

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
from tests.unit.test_remote_desktop_mouse import MockInputInjector
from tests.unit.test_remote_desktop_streaming import MockCaptureEngine, _recv_type


def _minimal_jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (128, 72), color=(10, 20, 30)).save(buffer, format="JPEG", quality=70)
    return buffer.getvalue()


async def _start_server(mock: MockInputInjector) -> RemoteDesktopWebSocketServer:
    server = RemoteDesktopWebSocketServer(
        device_id=TEST_DEVICE_ID,
        settings=_test_remote_desktop_settings(),
        jwt_secret=TEST_JWT_SECRET,
        capture_engine=MockCaptureEngine(),
        input_injector=mock,
    )
    await server.start()
    return server


def _ws_uri(server: RemoteDesktopWebSocketServer) -> str:
    port = server.bound_port
    assert port is not None
    settings = _test_remote_desktop_settings()
    return f"ws://127.0.0.1:{port}{settings.path}"


async def _authenticate_desktop_only(websocket: Any) -> None:
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


@pytest.mark.asyncio
async def test_mouse_blocked_without_mouse_permission() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate_desktop_only(websocket)
            await _send_json(websocket, "START_STREAM")
            await _recv_type(websocket, "START_STREAM")
            await _send_json(websocket, "MOUSE_MOVE", {"x": 0.5, "y": 0.5})
            await _send_json(websocket, "MOUSE_CLICK", {"button": "left"})
            await asyncio.sleep(0.1)
            assert mock.moves == []
            assert mock.clicks == []
    finally:
        await server.stop()
