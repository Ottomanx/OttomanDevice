from __future__ import annotations

import asyncio
from typing import Any

import pytest
from websockets.asyncio.client import connect

from ottomandevice.remote_desktop.auth import create_session_jwt
from ottomandevice.remote_desktop.clipboard_sync import parse_clipboard_text
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


class MockClipboardManager:
    def __init__(self, *, initial_text: str = "") -> None:
        self.content = initial_text
        self.reads = 0
        self.writes: list[str] = []

    def read(self) -> str:
        self.reads += 1
        return self.content

    def write(self, text: str) -> None:
        self.writes.append(text)
        self.content = text


async def _start_server(mock: MockClipboardManager) -> RemoteDesktopWebSocketServer:
    server = RemoteDesktopWebSocketServer(
        device_id=TEST_DEVICE_ID,
        settings=_test_remote_desktop_settings(),
        jwt_secret=TEST_JWT_SECRET,
        capture_engine=MockCaptureEngine(),
        input_injector=MockInputInjector(),
        clipboard_manager=mock,
    )
    await server.start()
    return server


def _ws_uri(server: RemoteDesktopWebSocketServer) -> str:
    port = server.bound_port
    assert port is not None
    settings = _test_remote_desktop_settings()
    return f"ws://127.0.0.1:{port}{settings.path}"


async def _authenticate(
    websocket: Any,
    *,
    permissions: list[str] | None = None,
) -> None:
    token = create_session_jwt(
        device_id=TEST_DEVICE_ID,
        secret=TEST_JWT_SECRET,
        ttl_seconds=60,
        permissions=permissions or ["desktop", "mouse", "keyboard", "clipboard"],
    )
    await _send_json(websocket, "HELLO")
    hello = await _recv_json(websocket)
    assert hello["type"] == "HELLO"

    await _send_json(websocket, "AUTH", {"token": token})
    auth = await _recv_json(websocket)
    assert auth["type"] == "AUTH"
    assert auth["payload"]["authenticated"] is True
    await _recv_json(websocket)


async def _start_stream(websocket: Any) -> None:
    await _authenticate(websocket)
    await _send_json(websocket, "START_STREAM")
    await _recv_type(websocket, "START_STREAM")


async def _drain_clipboard_changed(websocket: Any) -> None:
    while True:
        message = await _recv_json(websocket, timeout=0.2)
        if message["type"] != "CLIPBOARD_CHANGED":
            return message


@pytest.mark.asyncio
async def test_clipboard_read() -> None:
    mock = MockClipboardManager(initial_text="hello remote")
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _drain_clipboard_changed(websocket)
            await _send_json(websocket, "CLIPBOARD_GET")
            response = await _recv_json(websocket)
            assert response["type"] == "CLIPBOARD_GET"
            assert response["payload"]["text"] == "hello remote"
            assert mock.reads >= 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_clipboard_write() -> None:
    mock = MockClipboardManager()
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _drain_clipboard_changed(websocket)
            await _send_json(websocket, "CLIPBOARD_SET", {"text": "copied text"})
            changed = await _recv_json(websocket)
            assert changed["type"] == "CLIPBOARD_CHANGED"
            assert changed["payload"]["text"] == "copied text"
            assert mock.writes == ["copied text"]
            assert mock.content == "copied text"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_empty_clipboard_read() -> None:
    mock = MockClipboardManager(initial_text="")
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _drain_clipboard_changed(websocket)
            await _send_json(websocket, "CLIPBOARD_GET")
            response = await _recv_json(websocket)
            assert response["type"] == "CLIPBOARD_GET"
            assert response["payload"]["text"] == ""
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_unicode_clipboard() -> None:
    unicode_text = "caf\u00e9 \u2603"
    mock = MockClipboardManager(initial_text=unicode_text)
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _start_stream(websocket)
            await _drain_clipboard_changed(websocket)
            await _send_json(websocket, "CLIPBOARD_GET")
            response = await _recv_json(websocket)
            assert response["payload"]["text"] == unicode_text

            await _send_json(websocket, "CLIPBOARD_SET", {"text": unicode_text})
            changed = await _recv_json(websocket)
            assert changed["type"] == "CLIPBOARD_CHANGED"
            assert changed["payload"]["text"] == unicode_text
            assert mock.writes[-1] == unicode_text
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_clipboard_blocked_without_permission() -> None:
    mock = MockClipboardManager(initial_text="secret")
    server = await _start_server(mock)
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate(websocket, permissions=["desktop", "mouse"])
            await _send_json(websocket, "START_STREAM")
            await _recv_type(websocket, "START_STREAM")
            await _send_json(websocket, "CLIPBOARD_GET")
            await _send_json(websocket, "CLIPBOARD_SET", {"text": "blocked"})
            await asyncio.sleep(0.2)
            assert mock.reads == 0
            assert mock.writes == []
    finally:
        await server.stop()


def test_parse_clipboard_text_rejects_invalid() -> None:
    assert parse_clipboard_text(None) is None
    assert parse_clipboard_text(123) is None
    assert parse_clipboard_text("a\x00b") is None
    assert parse_clipboard_text("valid") == "valid"