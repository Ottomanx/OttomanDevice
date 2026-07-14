from __future__ import annotations

import asyncio
from typing import Any

import pytest
from websockets.asyncio.client import connect

from ottomandevice.remote_desktop.auth import create_session_jwt
from ottomandevice.remote_desktop.monitor.enumerator import DisplayEnumerator
from ottomandevice.remote_desktop.monitor.models import MonitorInfo
from ottomandevice.remote_desktop.websocket_server import RemoteDesktopWebSocketServer
from tests.unit.test_remote_desktop import (
    TEST_DEVICE_ID,
    TEST_JWT_SECRET,
    _recv_json,
    _send_json,
    _test_remote_desktop_settings,
)
from tests.unit.test_remote_desktop_streaming import MockCaptureEngine, _ws_uri


class TwoMonitorEnumerator(DisplayEnumerator):
    def enumerate(self) -> list[MonitorInfo]:
        return [
            MonitorInfo(
                id="display-1",
                number=1,
                width=1920,
                height=1080,
                x=0,
                y=0,
                is_primary=True,
            ),
            MonitorInfo(
                id="display-2",
                number=2,
                width=1280,
                height=720,
                x=1920,
                y=0,
                is_primary=False,
            ),
        ]


async def _authenticate(websocket: Any) -> None:
    token = create_session_jwt(
        device_id=TEST_DEVICE_ID,
        secret=TEST_JWT_SECRET,
        ttl_seconds=60,
        permissions=["desktop", "mouse"],
    )
    await _send_json(websocket, "HELLO")
    await _recv_json(websocket)
    await _send_json(websocket, "AUTH", {"token": token})
    await _recv_json(websocket)
    await _recv_json(websocket)


async def _recv_type(websocket: Any, expected: str, *, timeout: float = 5.0) -> dict[str, Any]:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        message = await _recv_json(
            websocket,
            timeout=max(0.1, deadline - asyncio.get_event_loop().time()),
        )
        if message["type"] == expected:
            return message
    raise TimeoutError(f"Timed out waiting for {expected}")


@pytest.mark.asyncio
async def test_monitor_list_after_start_stream() -> None:
    server = RemoteDesktopWebSocketServer(
        device_id=TEST_DEVICE_ID,
        settings=_test_remote_desktop_settings(),
        jwt_secret=TEST_JWT_SECRET,
        capture_engine=MockCaptureEngine(),
        display_enumerator=TwoMonitorEnumerator(),
    )
    await server.start()
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "START_STREAM")
            await _recv_type(websocket, "START_STREAM")
            monitor_list = await _recv_type(websocket, "MONITOR_LIST")
            monitors = monitor_list["payload"]["monitors"]
            assert len(monitors) == 2
            assert monitors[0]["number"] == 1
            assert monitors[0]["is_primary"] is True
            assert "thumbnail" not in monitors[0]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_monitor_select_switch() -> None:
    server = RemoteDesktopWebSocketServer(
        device_id=TEST_DEVICE_ID,
        settings=_test_remote_desktop_settings(),
        jwt_secret=TEST_JWT_SECRET,
        capture_engine=MockCaptureEngine(),
        display_enumerator=TwoMonitorEnumerator(),
    )
    await server.start()
    try:
        async with connect(
            _ws_uri(server),
            subprotocols=[_test_remote_desktop_settings().subprotocol],
        ) as websocket:
            await _authenticate(websocket)
            await _send_json(websocket, "START_STREAM")
            await _recv_type(websocket, "START_STREAM")
            await _recv_type(websocket, "MONITOR_LIST")
            await _send_json(websocket, "MONITOR_SELECT", {"monitor_id": "display-2"})
            ack = await _recv_type(websocket, "MONITOR_SELECT")
            assert ack["payload"]["accepted"] is True
            assert ack["payload"]["number"] == 2
    finally:
        await server.stop()
