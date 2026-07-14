from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from websockets.asyncio.client import connect

from ottomandevice.remote_desktop.auth import create_session_jwt
from ottomandevice.remote_desktop.websocket_server import RemoteDesktopWebSocketServer
from tests.unit.test_remote_desktop import (
    TEST_DEVICE_ID,
    TEST_JWT_SECRET,
    _recv_json,
    _send_json,
    _test_remote_desktop_settings,
    _wait_for_port,
)
from tests.unit.test_remote_desktop_streaming import MockCaptureEngine
from ottomandevice.remote_desktop import RemoteDesktopService


USER_A_ID = "user-a-1111"
USER_B_ID = "user-b-2222"
USER_A_NAME = "Alice Controller"
USER_B_NAME = "Bob Viewer"


def _token_for_user(
    user_id: str,
    *,
    controller_name: str | None = None,
    session_id: str | None = None,
) -> str:
    return create_session_jwt(
        device_id=TEST_DEVICE_ID,
        secret=TEST_JWT_SECRET,
        ttl_seconds=60,
        permissions=["desktop", "mouse", "keyboard"],
        user_id=user_id,
        controller_name=controller_name,
        session_id=session_id,
    )


async def _start_server() -> RemoteDesktopWebSocketServer:
    server = RemoteDesktopWebSocketServer(
        device_id=TEST_DEVICE_ID,
        settings=_test_remote_desktop_settings(),
        jwt_secret=TEST_JWT_SECRET,
        capture_engine=MockCaptureEngine(),
    )
    await server.start()
    return server


def _ws_uri(server: RemoteDesktopWebSocketServer) -> str:
    port = server.bound_port
    assert port is not None
    settings = _test_remote_desktop_settings()
    return f"ws://127.0.0.1:{port}{settings.path}"


async def _authenticate_user(
    websocket: Any,
    user_id: str,
    *,
    controller_name: str | None = None,
) -> dict[str, Any]:
    token = _token_for_user(user_id, controller_name=controller_name)
    await _send_json(websocket, "HELLO")
    hello = await _recv_json(websocket)
    assert hello["type"] == "HELLO"

    await _send_json(websocket, "AUTH", {"token": token})
    auth = await _recv_json(websocket)
    assert auth["type"] == "AUTH"
    assert auth["payload"]["authenticated"] is True
    return auth


async def _expect_session_info(
    websocket: Any,
    *,
    user_id: str,
    controller_name: str,
) -> dict[str, Any]:
    message = await _recv_json(websocket)
    assert message["type"] == "SESSION_INFO"
    payload = message["payload"]
    assert payload["active"] is True
    assert payload["user_id"] == user_id
    assert payload["controller_name"] == controller_name
    assert isinstance(payload["session_id"], str)
    assert isinstance(payload["started_at"], int)
    return payload


@pytest.mark.asyncio
async def test_two_users_connect_second_receives_session_info() -> None:
    server = await _start_server()
    try:
        settings = _test_remote_desktop_settings()
        async with connect(_ws_uri(server), subprotocols=[settings.subprotocol]) as first:
            await _authenticate_user(first, USER_A_ID, controller_name=USER_A_NAME)
            await _expect_session_info(
                first,
                user_id=USER_A_ID,
                controller_name=USER_A_NAME,
            )

            async with connect(_ws_uri(server), subprotocols=[settings.subprotocol]) as second:
                session_info = await _recv_json(second)
                assert session_info["type"] == "SESSION_INFO"
                assert session_info["payload"]["active"] is True
                assert session_info["payload"]["user_id"] == USER_A_ID
                assert session_info["payload"]["controller_name"] == USER_A_NAME

                busy = await _recv_json(second)
                assert busy["type"] == "ERROR"
                assert busy["payload"]["code"] == "SESSION_BUSY"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_second_user_rejected_while_first_controls() -> None:
    server = await _start_server()
    try:
        settings = _test_remote_desktop_settings()
        async with connect(_ws_uri(server), subprotocols=[settings.subprotocol]) as first:
            await _authenticate_user(first, USER_A_ID, controller_name=USER_A_NAME)
            await _expect_session_info(first, user_id=USER_A_ID, controller_name=USER_A_NAME)

            async with connect(_ws_uri(server), subprotocols=[settings.subprotocol]) as second:
                await _recv_json(second)
                response = await _recv_json(second)
                assert response["type"] == "ERROR"
                assert response["payload"]["code"] == "SESSION_BUSY"

            await _send_json(first, "PING")
            pong = await _recv_json(first)
            assert pong["type"] == "PONG"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_disconnect_releases_session_for_next_user() -> None:
    server = await _start_server()
    try:
        settings = _test_remote_desktop_settings()
        uri = _ws_uri(server)

        async with connect(uri, subprotocols=[settings.subprotocol]) as first:
            await _authenticate_user(first, USER_A_ID, controller_name=USER_A_NAME)
            await _expect_session_info(first, user_id=USER_A_ID, controller_name=USER_A_NAME)

        await asyncio.sleep(0.1)

        async with connect(uri, subprotocols=[settings.subprotocol]) as second:
            await _authenticate_user(second, USER_B_ID, controller_name=USER_B_NAME)
            info = await _expect_session_info(
                second,
                user_id=USER_B_ID,
                controller_name=USER_B_NAME,
            )
            assert info["user_id"] == USER_B_ID
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_timeout_releases_session_for_next_user() -> None:
    remote_desktop_settings = _test_remote_desktop_settings()
    service = RemoteDesktopService(
        device_id=TEST_DEVICE_ID,
        jwt_secret=TEST_JWT_SECRET,
        remote_desktop_settings=remote_desktop_settings,
    )
    service.start()
    try:
        port = await _wait_for_port(service)
        uri = f"ws://127.0.0.1:{port}/remote-desktop/v1"
        token = _token_for_user(USER_A_ID, controller_name=USER_A_NAME)

        async with connect(uri, subprotocols=[remote_desktop_settings.subprotocol]) as first:
            await _send_json(first, "HELLO")
            await _recv_json(first)
            await _send_json(first, "AUTH", {"token": token})
            await _recv_json(first)
            await _recv_json(first)

            deadline = time.monotonic() + 8.0
            saw_release = False
            saw_timeout = False
            while time.monotonic() < deadline:
                message = await _recv_json(
                    first,
                    timeout=max(0.1, deadline - time.monotonic()),
                )
                if message["type"] == "SESSION_RELEASE":
                    saw_release = True
                if (
                    message["type"] == "ERROR"
                    and message["payload"].get("code") == "TIMEOUT"
                ):
                    saw_timeout = True
                    break

            assert saw_release is True
            assert saw_timeout is True

        await asyncio.sleep(0.1)

        token_b = _token_for_user(USER_B_ID, controller_name=USER_B_NAME)
        async with connect(uri, subprotocols=[remote_desktop_settings.subprotocol]) as second:
            await _send_json(second, "HELLO")
            await _recv_json(second)
            await _send_json(second, "AUTH", {"token": token_b})
            auth = await _recv_json(second)
            assert auth["type"] == "AUTH"
            info = await _recv_json(second)
            assert info["type"] == "SESSION_INFO"
            assert info["payload"]["user_id"] == USER_B_ID
    finally:
        service.stop()


@pytest.mark.asyncio
async def test_client_session_release_allows_next_user() -> None:
    server = await _start_server()
    try:
        settings = _test_remote_desktop_settings()
        uri = _ws_uri(server)

        async with connect(uri, subprotocols=[settings.subprotocol]) as first:
            await _authenticate_user(first, USER_A_ID, controller_name=USER_A_NAME)
            await _expect_session_info(first, user_id=USER_A_ID, controller_name=USER_A_NAME)
            await _send_json(first, "SESSION_RELEASE")
            release = await _recv_json(first)
            assert release["type"] == "SESSION_RELEASE"

        await asyncio.sleep(0.1)

        async with connect(uri, subprotocols=[settings.subprotocol]) as second:
            await _authenticate_user(second, USER_B_ID, controller_name=USER_B_NAME)
            await _expect_session_info(second, user_id=USER_B_ID, controller_name=USER_B_NAME)
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_session_info_query_returns_active_controller() -> None:
    server = await _start_server()
    try:
        settings = _test_remote_desktop_settings()
        async with connect(_ws_uri(server), subprotocols=[settings.subprotocol]) as websocket:
            await _authenticate_user(websocket, USER_A_ID, controller_name=USER_A_NAME)
            await _expect_session_info(websocket, user_id=USER_A_ID, controller_name=USER_A_NAME)

            await _send_json(websocket, "SESSION_INFO")
            response = await _recv_json(websocket)
            assert response["type"] == "SESSION_INFO"
            assert response["payload"]["active"] is True
            assert response["payload"]["user_id"] == USER_A_ID
    finally:
        await server.stop()