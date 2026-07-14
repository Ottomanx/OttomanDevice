from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator

import pytest
from io import BytesIO

from PIL import Image
from websockets.asyncio.client import connect

from ottomandevice.config.settings import RemoteDesktopSettings, FileTransferSettings
from ottomandevice.remote_desktop import RemoteDesktopService
from ottomandevice.remote_desktop.auth import create_session_jwt
from ottomandevice.remote_desktop.session import RemoteDesktopSession, SessionState
from ottomandevice.remote_desktop.websocket_server import RemoteDesktopWebSocketServer

TEST_DEVICE_ID = "test-device-001"
TEST_JWT_SECRET = "test-remote-desktop-jwt-secret"


def _minimal_jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (128, 72), color=(10, 20, 30)).save(buffer, format="JPEG", quality=70)
    return buffer.getvalue()


class MockCaptureEngine:
    def capture_and_encode(self) -> tuple[bytes, int, int]:
        return _minimal_jpeg_bytes(), 128, 72



def _test_remote_desktop_settings() -> RemoteDesktopSettings:
    return RemoteDesktopSettings(
        host="127.0.0.1",
        port=0,
        path="/remote-desktop/v1",
        subprotocol="ottoman-remote-desktop.v1",
        ping_interval=1,
        disconnect_timeout=2,
        token_ttl_seconds=60,
        jwt_secret_env="REMOTE_DESKTOP_JWT_SECRET",
        jwt_algorithm="HS256",
        fps=10,
        jpeg_quality=70,
        width=128,
        clipboard_poll_interval_ms=300,
        file_transfer=FileTransferSettings(
            workspace_dir="data/test-workspace",
            max_file_size_bytes=104857600,
            chunk_size=65536,
        ),
    )


@pytest.fixture
def remote_desktop_settings() -> RemoteDesktopSettings:
    return _test_remote_desktop_settings()


async def _wait_for_port(service: RemoteDesktopService, timeout: float = 5.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        port = service.bound_port
        if port:
            return port
        await asyncio.sleep(0.05)
    raise TimeoutError("Remote desktop server did not bind a port")


async def _recv_json(websocket: Any, timeout: float = 5.0) -> dict[str, Any]:
    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    message = json.loads(raw)
    assert isinstance(message, dict)
    return message


async def _send_json(websocket: Any, msg_type: str, payload: dict[str, Any] | None = None) -> None:
    await websocket.send(
        json.dumps(
            {
                "type": msg_type,
                "session_id": None,
                "seq": 1,
                "ts": int(time.time() * 1000),
                "payload": payload or {},
            }
        )
    )


@pytest.fixture
async def running_service(
    remote_desktop_settings: RemoteDesktopSettings,
) -> AsyncIterator[RemoteDesktopService]:
    service = RemoteDesktopService(
        device_id=TEST_DEVICE_ID,
        jwt_secret=TEST_JWT_SECRET,
        remote_desktop_settings=remote_desktop_settings,
        capture_engine=MockCaptureEngine(),
    )
    service.start()
    try:
        await _wait_for_port(service)
        yield service
    finally:
        service.stop()


@pytest.mark.asyncio
async def test_connection(running_service: RemoteDesktopService) -> None:
    port = running_service.bound_port
    assert port is not None

    uri = f"ws://127.0.0.1:{port}/remote-desktop/v1"
    async with connect(
        uri,
        subprotocols=[_test_remote_desktop_settings().subprotocol],
    ) as websocket:
        await _send_json(websocket, "HELLO")
        response = await _recv_json(websocket)
        assert response["type"] == "HELLO"
        assert response["payload"]["device_id"] == TEST_DEVICE_ID
        assert response["session_id"]


@pytest.mark.asyncio
async def test_authentication_success(running_service: RemoteDesktopService) -> None:
    port = running_service.bound_port
    assert port is not None

    token = create_session_jwt(device_id=TEST_DEVICE_ID, secret=TEST_JWT_SECRET, ttl_seconds=60)
    uri = f"ws://127.0.0.1:{port}/remote-desktop/v1"

    async with connect(
        uri,
        subprotocols=[_test_remote_desktop_settings().subprotocol],
    ) as websocket:
        await _send_json(websocket, "HELLO")
        await _recv_json(websocket)

        await _send_json(websocket, "AUTH", {"token": token})
        response = await _recv_json(websocket)
        assert response["type"] == "AUTH"
        assert response["payload"]["authenticated"] is True


@pytest.mark.asyncio
async def test_authentication_rejects_invalid_token(
    running_service: RemoteDesktopService,
) -> None:
    port = running_service.bound_port
    assert port is not None

    uri = f"ws://127.0.0.1:{port}/remote-desktop/v1"

    async with connect(
        uri,
        subprotocols=[_test_remote_desktop_settings().subprotocol],
    ) as websocket:
        await _send_json(websocket, "HELLO")
        await _recv_json(websocket)

        await _send_json(websocket, "AUTH", {"token": "invalid.token"})
        response = await _recv_json(websocket)
        assert response["type"] == "ERROR"
        assert response["payload"]["code"] == "AUTH_FAILED"


@pytest.mark.asyncio
async def test_ping_pong(running_service: RemoteDesktopService) -> None:
    port = running_service.bound_port
    assert port is not None

    token = create_session_jwt(device_id=TEST_DEVICE_ID, secret=TEST_JWT_SECRET, ttl_seconds=60)
    uri = f"ws://127.0.0.1:{port}/remote-desktop/v1"

    async with connect(
        uri,
        subprotocols=[_test_remote_desktop_settings().subprotocol],
    ) as websocket:
        await _send_json(websocket, "HELLO")
        await _recv_json(websocket)
        await _send_json(websocket, "AUTH", {"token": token})
        await _recv_json(websocket)
        session_info = await _recv_json(websocket)
        assert session_info["type"] == "SESSION_INFO"

        await _send_json(websocket, "PING")
        response = await _recv_json(websocket)
        assert response["type"] == "PONG"

        server_ping = await _recv_json(websocket, timeout=3.0)
        assert server_ping["type"] == "PING"
        await _send_json(websocket, "PONG")
        await asyncio.sleep(0.2)


@pytest.mark.asyncio
async def test_timeout_disconnects_inactive_client(
    remote_desktop_settings: RemoteDesktopSettings,
) -> None:
    service = RemoteDesktopService(
        device_id=TEST_DEVICE_ID,
        jwt_secret=TEST_JWT_SECRET,
        remote_desktop_settings=remote_desktop_settings,
    )
    service.start()
    try:
        port = await _wait_for_port(service)
        token = create_session_jwt(device_id=TEST_DEVICE_ID, secret=TEST_JWT_SECRET, ttl_seconds=60)
        uri = f"ws://127.0.0.1:{port}/remote-desktop/v1"

        async with connect(
            uri,
            subprotocols=[remote_desktop_settings.subprotocol],
        ) as websocket:
            await _send_json(websocket, "HELLO")
            await _recv_json(websocket)
            await _send_json(websocket, "AUTH", {"token": token})
            await _recv_json(websocket)

            deadline = time.monotonic() + 8.0
            error_message: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                message = await _recv_json(
                    websocket,
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                if message["type"] == "ERROR" and message["payload"].get("code") == "TIMEOUT":
                    error_message = message
                    break

            assert error_message is not None
            assert error_message["type"] == "ERROR"
            assert error_message["payload"]["code"] == "TIMEOUT"
    finally:
        service.stop()


@pytest.mark.asyncio
async def test_unsupported_message_returns_not_implemented(
    running_service: RemoteDesktopService,
) -> None:
    port = running_service.bound_port
    assert port is not None

    uri = f"ws://127.0.0.1:{port}/remote-desktop/v1"

    async with connect(
        uri,
        subprotocols=[_test_remote_desktop_settings().subprotocol],
    ) as websocket:
        await _send_json(websocket, "MOUSE", {"action": "move"})
        response = await _recv_json(websocket)
        assert response["type"] == "ERROR"
        assert response["payload"]["message"] == "Not implemented"


@pytest.mark.asyncio
async def test_graceful_shutdown(remote_desktop_settings: RemoteDesktopSettings) -> None:
    service = RemoteDesktopService(
        device_id=TEST_DEVICE_ID,
        jwt_secret=TEST_JWT_SECRET,
        remote_desktop_settings=remote_desktop_settings,
    )
    service.start()
    port = await _wait_for_port(service)

    uri = f"ws://127.0.0.1:{port}/remote-desktop/v1"
    async with connect(
        uri,
        subprotocols=[remote_desktop_settings.subprotocol],
    ) as websocket:
        await _send_json(websocket, "HELLO")
        await _recv_json(websocket)

        service.stop()
        with pytest.raises(Exception):
            await asyncio.wait_for(websocket.recv(), timeout=3.0)


def test_session_state_machine_transitions() -> None:
    session = RemoteDesktopSession(session_id="session-1")
    assert session.state == SessionState.IDLE

    session.mark_connecting()
    assert session.state == SessionState.CONNECTING

    session.mark_authenticated()
    assert session.state == SessionState.AUTHENTICATED

    session.mark_active()
    assert session.state == SessionState.ACTIVE

    session.mark_disconnected()
    assert session.state == SessionState.DISCONNECTED


@pytest.mark.asyncio
async def test_direct_server_rejects_busy_session(
    remote_desktop_settings: RemoteDesktopSettings,
) -> None:
    server = RemoteDesktopWebSocketServer(
        device_id=TEST_DEVICE_ID,
        settings=remote_desktop_settings,
        jwt_secret=TEST_JWT_SECRET,
        capture_engine=MockCaptureEngine(),
    )
    await server.start()
    try:
        port = server.bound_port
        assert port is not None
        uri = f"ws://127.0.0.1:{port}/remote-desktop/v1"

        token = create_session_jwt(
            device_id=TEST_DEVICE_ID,
            secret=TEST_JWT_SECRET,
            ttl_seconds=60,
        )
        async with connect(
            uri,
            subprotocols=[remote_desktop_settings.subprotocol],
        ) as first:
            await _send_json(first, "HELLO")
            await _recv_json(first)
            await _send_json(first, "AUTH", {"token": token})
            await _recv_json(first)
            await _recv_json(first)

            async with connect(
                uri,
                subprotocols=[remote_desktop_settings.subprotocol],
            ) as second:
                session_info = await _recv_json(second)
                assert session_info["type"] == "SESSION_INFO"
                response = await _recv_json(second)
                assert response["type"] == "ERROR"
                assert response["payload"]["code"] == "SESSION_BUSY"
    finally:
        await server.stop()
