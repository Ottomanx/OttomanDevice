from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.client import connect

from ottomandevice.remote_desktop.auth import create_session_jwt
from ottomandevice.remote_desktop.file_transfer import FileTransferManager
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


async def _start_server(workspace: Path) -> RemoteDesktopWebSocketServer:
    settings = _test_remote_desktop_settings()
    server = RemoteDesktopWebSocketServer(
        device_id=TEST_DEVICE_ID,
        settings=settings,
        jwt_secret=TEST_JWT_SECRET,
        capture_engine=MockCaptureEngine(),
        input_injector=MockInputInjector(),
        file_transfer_manager=FileTransferManager(
            workspace_dir=workspace,
            max_file_size_bytes=settings.file_transfer.max_file_size_bytes,
            chunk_size=settings.file_transfer.chunk_size,
        ),
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
        permissions=permissions
        or ["desktop", "mouse", "keyboard", "clipboard", "file_transfer"],
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


async def _recv_transfer_type(
    websocket: Any,
    expected: str,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
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
async def test_file_upload() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        server = await _start_server(workspace)
        try:
            async with connect(
                _ws_uri(server),
                subprotocols=[_test_remote_desktop_settings().subprotocol],
            ) as websocket:
                await _start_stream(websocket)
                transfer_id = "upload-1"
                payload = b"hello upload"
                await _send_json(
                    websocket,
                    "FILE_UPLOAD",
                    {
                        "transfer_id": transfer_id,
                        "path": "docs/hello.txt",
                        "size": len(payload),
                    },
                )
                progress = await _recv_transfer_type(websocket, "FILE_PROGRESS")
                assert progress["payload"]["total"] == len(payload)

                await _send_json(
                    websocket,
                    "FILE_UPLOAD",
                    {
                        "transfer_id": transfer_id,
                        "chunk": base64.b64encode(payload).decode("ascii"),
                    },
                )
                await _recv_transfer_type(websocket, "FILE_PROGRESS")
                complete = await _recv_transfer_type(websocket, "FILE_COMPLETE")
                assert complete["payload"]["path"] == "docs/hello.txt"
                assert (workspace / "docs" / "hello.txt").read_bytes() == payload
        finally:
            await server.stop()


@pytest.mark.asyncio
async def test_file_download() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        target = workspace / "reports" / "summary.txt"
        target.parent.mkdir(parents=True)
        payload = b"download me"
        target.write_bytes(payload)

        server = await _start_server(workspace)
        try:
            async with connect(
                _ws_uri(server),
                subprotocols=[_test_remote_desktop_settings().subprotocol],
            ) as websocket:
                await _start_stream(websocket)
                transfer_id = "download-1"
                await _send_json(
                    websocket,
                    "FILE_DOWNLOAD",
                    {
                        "transfer_id": transfer_id,
                        "path": "reports/summary.txt",
                    },
                )

                chunks: list[bytes] = []
                while True:
                    message = await _recv_json(websocket)
                    if message["type"] == "FILE_DOWNLOAD":
                        chunks.append(
                            base64.b64decode(message["payload"]["chunk"], validate=True)
                        )
                        if message["payload"].get("final") is True:
                            break
                    elif message["type"] == "FILE_COMPLETE":
                        break

                assert b"".join(chunks) == payload
        finally:
            await server.stop()


@pytest.mark.asyncio
async def test_file_transfer_permission_denied() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        server = await _start_server(workspace)
        try:
            async with connect(
                _ws_uri(server),
                subprotocols=[_test_remote_desktop_settings().subprotocol],
            ) as websocket:
                await _authenticate(websocket, permissions=["desktop", "mouse"])
                await _send_json(websocket, "START_STREAM")
                await _recv_type(websocket, "START_STREAM")
                await _send_json(
                    websocket,
                    "FILE_UPLOAD",
                    {
                        "transfer_id": "denied-1",
                        "path": "secret.txt",
                        "size": 4,
                    },
                )
                await asyncio.sleep(0.2)
                assert list(workspace.glob("**/*")) == []
        finally:
            await server.stop()


@pytest.mark.asyncio
async def test_invalid_path_rejected() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        server = await _start_server(workspace)
        try:
            async with connect(
                _ws_uri(server),
                subprotocols=[_test_remote_desktop_settings().subprotocol],
            ) as websocket:
                await _start_stream(websocket)
                await _send_json(
                    websocket,
                    "FILE_UPLOAD",
                    {
                        "transfer_id": "bad-path",
                        "path": "../outside.txt",
                        "size": 4,
                    },
                )
                error = await _recv_transfer_type(websocket, "FILE_ERROR")
                assert error["payload"]["code"] == "INVALID_PATH"
        finally:
            await server.stop()


@pytest.mark.asyncio
async def test_large_file_rejected() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        server = await _start_server(workspace)
        try:
            settings = _test_remote_desktop_settings()
            oversized = settings.file_transfer.max_file_size_bytes + 1
            async with connect(
                _ws_uri(server),
                subprotocols=[settings.subprotocol],
            ) as websocket:
                await _start_stream(websocket)
                await _send_json(
                    websocket,
                    "FILE_UPLOAD",
                    {
                        "transfer_id": "large-1",
                        "path": "big.bin",
                        "size": oversized,
                    },
                )
                error = await _recv_transfer_type(websocket, "FILE_ERROR")
                assert error["payload"]["code"] == "FILE_TOO_LARGE"
        finally:
            await server.stop()


@pytest.mark.asyncio
async def test_cancel_upload_transfer() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        server = await _start_server(workspace)
        try:
            async with connect(
                _ws_uri(server),
                subprotocols=[_test_remote_desktop_settings().subprotocol],
            ) as websocket:
                await _start_stream(websocket)
                transfer_id = "cancel-upload"
                await _send_json(
                    websocket,
                    "FILE_UPLOAD",
                    {
                        "transfer_id": transfer_id,
                        "path": "cancel.txt",
                        "size": 32,
                    },
                )
                await _recv_transfer_type(websocket, "FILE_PROGRESS")
                await _send_json(
                    websocket,
                    "FILE_UPLOAD",
                    {"transfer_id": transfer_id, "cancel": True},
                )
                error = await _recv_transfer_type(websocket, "FILE_ERROR")
                assert error["payload"]["code"] == "CANCELLED"
                assert not (workspace / "cancel.txt").exists()
        finally:
            await server.stop()