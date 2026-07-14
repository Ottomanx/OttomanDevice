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
from tests.unit.test_remote_desktop_streaming import (
    MockCaptureEngine,
    _recv_type,
)


async def _authenticate(websocket: Any) -> None:
    token = create_session_jwt(
        device_id=TEST_DEVICE_ID,
        secret=TEST_JWT_SECRET,
        ttl_seconds=60,
        permissions=["desktop", "mouse"],
    )
    await _send_json(websocket, "HELLO")
    hello = await _recv_json(websocket)
    assert hello["type"] == "HELLO"

    await _send_json(websocket, "AUTH", {"token": token})
    auth = await _recv_json(websocket)
    assert auth["type"] == "AUTH"
    assert auth["payload"]["authenticated"] is True



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


class MockInputInjector:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []
        self.clicks: list[str] = []
        self.left_clicks = 0
        self.right_clicks = 0
        self.double_clicks = 0
        self.scrolls: list[int] = []

    def move(self, x: float, y: float) -> None:
        self.moves.append((x, y))

    def left_click(self) -> None:
        self.left_clicks += 1
        self.clicks.append("left")

    def right_click(self) -> None:
        self.right_clicks += 1
        self.clicks.append("right")

    def double_click(self) -> None:
        self.double_clicks += 1

    def scroll(self, delta: int) -> None:
        self.scrolls.append(delta)

    def click(self, button: str) -> None:
        if button == "left":
            self.left_click()
            return
        if button == "right":
            self.right_click()
            return
        raise ValueError(f"unsupported button: {button}")


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


async def _start_stream(websocket: Any) -> None:
    await _authenticate(websocket)
    await _send_json(websocket, "START_STREAM")
    await _recv_type(websocket, "START_STREAM")


@pytest.mark.asyncio
async def test_mouse_move_when_stream_active() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _send_json(websocket, "MOUSE_MOVE", {"x": 0.25, "y": 0.75})
            await asyncio.sleep(0.1)
            assert mock.moves == [(0.25, 0.75)]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_mouse_left_click() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _send_json(websocket, "MOUSE_CLICK", {"button": "left"})
            await asyncio.sleep(0.1)
            assert mock.left_clicks == 1
            assert mock.clicks == ["left"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_mouse_right_click() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _send_json(websocket, "MOUSE_CLICK", {"button": "right"})
            await asyncio.sleep(0.1)
            assert mock.right_clicks == 1
            assert mock.clicks == ["right"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_invalid_coordinates_ignored() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _send_json(websocket, "MOUSE_MOVE", {"x": "bad", "y": 0.5})
            await asyncio.sleep(0.1)
            assert mock.moves == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_mouse_events_ignored_when_stream_inactive() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "MOUSE_MOVE", {"x": 0.5, "y": 0.5})
            await asyncio.sleep(0.1)
            assert mock.moves == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_out_of_range_coordinates_rejected() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _send_json(websocket, "MOUSE_MOVE", {"x": 1.5, "y": -0.2})
            await asyncio.sleep(0.1)
            assert mock.moves == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_mouse_double_click() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _send_json(websocket, "MOUSE_DOUBLE_CLICK")
            await asyncio.sleep(0.1)
            assert mock.double_clicks == 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_mouse_scroll_up_and_down() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _send_json(websocket, "MOUSE_SCROLL", {"delta": 120})
            await _send_json(websocket, "MOUSE_SCROLL", {"delta": -120})
            await asyncio.sleep(0.1)
            assert mock.scrolls == [120, -120]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_mouse_events_rejected_before_authentication() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _send_json(websocket, "HELLO")
            await _recv_json(websocket)
            await _send_json(websocket, "MOUSE_MOVE", {"x": 0.5, "y": 0.5})
            await _send_json(websocket, "MOUSE_CLICK", {"button": "left"})
            await asyncio.sleep(0.1)
            assert mock.moves == []
            assert mock.clicks == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_malformed_mouse_packets_ignored() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _send_json(websocket, "MOUSE_CLICK", {"button": "middle"})
            await _send_json(websocket, "MOUSE_SCROLL", {"delta": 0})
            await asyncio.sleep(0.1)
            assert mock.clicks == []
            assert mock.scrolls == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_top_level_mouse_move_fields_supported() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await websocket.send(
                '{"type":"MOUSE_MOVE","x":0.53,"y":0.41,"session_id":null,"seq":1,"ts":1,"payload":{}}'
            )
            await asyncio.sleep(0.1)
            assert mock.moves == [(0.53, 0.41)]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_mouse_events_ignored_after_stream_stopped() -> None:
    mock = MockInputInjector()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _send_json(websocket, "STOP_STREAM")
            await _recv_type(websocket, "STOP_STREAM")
            await _send_json(websocket, "MOUSE_MOVE", {"x": 0.5, "y": 0.5})
            await asyncio.sleep(0.1)
            assert mock.moves == []
    finally:
        await server.stop()
