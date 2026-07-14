from __future__ import annotations

import time
from io import BytesIO
from typing import Any

import pytest
from PIL import Image
from websockets.asyncio.client import connect

from ottomandevice.remote_desktop.auth import TokenReplayGuard, create_session_jwt
from ottomandevice.remote_desktop.websocket_server import RemoteDesktopWebSocketServer
from tests.unit.test_remote_desktop import (
    TEST_DEVICE_ID,
    TEST_JWT_SECRET,
    _recv_json,
    _send_json,
    _test_remote_desktop_settings,
)


def _minimal_jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (128, 72), color=(10, 20, 30)).save(buffer, format="JPEG", quality=70)
    return buffer.getvalue()


class MockCaptureEngine:
    def capture_and_encode(self) -> tuple[bytes, int, int]:
        return _minimal_jpeg_bytes(), 128, 72


async def _start_auth_server(
    *,
    replay_guard: TokenReplayGuard | None = None,
) -> RemoteDesktopWebSocketServer:
    settings = _test_remote_desktop_settings()
    server = RemoteDesktopWebSocketServer(
        device_id=TEST_DEVICE_ID,
        settings=settings,
        jwt_secret=TEST_JWT_SECRET,
        capture_engine=MockCaptureEngine(),
        replay_guard=replay_guard,
    )
    await server.start()
    return server


def _ws_uri(server: RemoteDesktopWebSocketServer) -> str:
    port = server.bound_port
    assert port is not None
    settings = _test_remote_desktop_settings()
    return f"ws://127.0.0.1:{port}{settings.path}"


async def _hello(websocket: Any) -> None:
    await _send_json(websocket, "HELLO")
    response = await _recv_json(websocket)
    assert response["type"] == "HELLO"


async def _auth_with_token(websocket: Any, token: str) -> dict[str, Any]:
    await _send_json(websocket, "AUTH", {"token": token})
    return await _recv_json(websocket)


@pytest.mark.asyncio
async def test_valid_token_authenticates() -> None:
    server = await _start_auth_server()
    try:
        token = create_session_jwt(
            device_id=TEST_DEVICE_ID,
            secret=TEST_JWT_SECRET,
            ttl_seconds=60,
        )
        settings = _test_remote_desktop_settings()
        async with connect(_ws_uri(server), subprotocols=[settings.subprotocol]) as websocket:
            await _hello(websocket)
            response = await _auth_with_token(websocket, token)
            assert response["type"] == "AUTH"
            assert response["payload"]["authenticated"] is True
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_expired_token_rejected() -> None:
    server = await _start_auth_server()
    try:
        issued_at = int(time.time()) - 120
        token = create_session_jwt(
            device_id=TEST_DEVICE_ID,
            secret=TEST_JWT_SECRET,
            ttl_seconds=60,
            issued_at=issued_at,
        )
        settings = _test_remote_desktop_settings()
        async with connect(_ws_uri(server), subprotocols=[settings.subprotocol]) as websocket:
            await _hello(websocket)
            response = await _auth_with_token(websocket, token)
            assert response["type"] == "ERROR"
            assert response["payload"]["code"] == "TOKEN_EXPIRED"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_invalid_signature_rejected() -> None:
    server = await _start_auth_server()
    try:
        token = create_session_jwt(
            device_id=TEST_DEVICE_ID,
            secret="wrong-signing-secret",
            ttl_seconds=60,
        )
        settings = _test_remote_desktop_settings()
        async with connect(_ws_uri(server), subprotocols=[settings.subprotocol]) as websocket:
            await _hello(websocket)
            response = await _auth_with_token(websocket, token)
            assert response["type"] == "ERROR"
            assert response["payload"]["code"] == "AUTH_FAILED"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_reused_token_rejected() -> None:
    replay_guard = TokenReplayGuard()
    server = await _start_auth_server(replay_guard=replay_guard)
    try:
        token = create_session_jwt(
            device_id=TEST_DEVICE_ID,
            secret=TEST_JWT_SECRET,
            ttl_seconds=60,
        )
        settings = _test_remote_desktop_settings()
        uri = _ws_uri(server)

        async with connect(uri, subprotocols=[settings.subprotocol]) as first:
            await _hello(first)
            first_auth = await _auth_with_token(first, token)
            assert first_auth["type"] == "AUTH"
            assert first_auth["payload"]["authenticated"] is True

        async with connect(uri, subprotocols=[settings.subprotocol]) as second:
            await _hello(second)
            second_auth = await _auth_with_token(second, token)
            assert second_auth["type"] == "ERROR"
            assert second_auth["payload"]["code"] == "TOKEN_REUSED"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_wrong_device_rejected() -> None:
    server = await _start_auth_server()
    try:
        token = create_session_jwt(
            device_id="other-device-id",
            secret=TEST_JWT_SECRET,
            ttl_seconds=60,
        )
        settings = _test_remote_desktop_settings()
        async with connect(_ws_uri(server), subprotocols=[settings.subprotocol]) as websocket:
            await _hello(websocket)
            response = await _auth_with_token(websocket, token)
            assert response["type"] == "ERROR"
            assert response["payload"]["code"] == "AUTH_FAILED"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_automatic_renewal_with_new_jti() -> None:
    replay_guard = TokenReplayGuard()
    server = await _start_auth_server(replay_guard=replay_guard)
    try:
        settings = _test_remote_desktop_settings()
        uri = _ws_uri(server)

        token_one = create_session_jwt(
            device_id=TEST_DEVICE_ID,
            secret=TEST_JWT_SECRET,
            ttl_seconds=60,
            jti="renewal-jti-1",
        )
        async with connect(uri, subprotocols=[settings.subprotocol]) as websocket:
            await _hello(websocket)
            first = await _auth_with_token(websocket, token_one)
            assert first["type"] == "AUTH"
            assert first["payload"]["authenticated"] is True

        token_two = create_session_jwt(
            device_id=TEST_DEVICE_ID,
            secret=TEST_JWT_SECRET,
            ttl_seconds=60,
            jti="renewal-jti-2",
        )
        async with connect(uri, subprotocols=[settings.subprotocol]) as websocket:
            await _hello(websocket)
            second = await _auth_with_token(websocket, token_two)
            assert second["type"] == "AUTH"
            assert second["payload"]["authenticated"] is True
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_reconnect_after_renewal() -> None:
    replay_guard = TokenReplayGuard()
    server = await _start_auth_server(replay_guard=replay_guard)
    try:
        settings = _test_remote_desktop_settings()
        uri = _ws_uri(server)

        initial_token = create_session_jwt(
            device_id=TEST_DEVICE_ID,
            secret=TEST_JWT_SECRET,
            ttl_seconds=60,
            jti="reconnect-jti-1",
        )
        async with connect(uri, subprotocols=[settings.subprotocol]) as websocket:
            await _hello(websocket)
            initial = await _auth_with_token(websocket, initial_token)
            assert initial["type"] == "AUTH"

        renewed_token = create_session_jwt(
            device_id=TEST_DEVICE_ID,
            secret=TEST_JWT_SECRET,
            ttl_seconds=60,
            jti="reconnect-jti-2",
        )
        async with connect(uri, subprotocols=[settings.subprotocol]) as websocket:
            await _hello(websocket)
            renewed = await _auth_with_token(websocket, renewed_token)
            assert renewed["type"] == "AUTH"
            assert renewed["payload"]["authenticated"] is True
    finally:
        await server.stop()