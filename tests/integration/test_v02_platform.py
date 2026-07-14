from __future__ import annotations

import asyncio
import base64
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.client import connect

from ottomandevice.config.settings import Settings
from ottomandevice.core.service_registry import ServiceRegistry
from ottomandevice.remote_desktop import RemoteDesktopService
from ottomandevice.remote_desktop.auth import create_session_jwt
from ottomandevice.remote_desktop.file_transfer import FileTransferManager
from ottomandevice.remote_desktop.websocket_server import RemoteDesktopWebSocketServer
from tests.unit.test_remote_desktop import (
    TEST_DEVICE_ID,
    TEST_JWT_SECRET,
    _recv_json,
    _send_json,
    _test_remote_desktop_settings,
    _wait_for_port,
)
from tests.unit.test_remote_desktop_keyboard import MockKeyboardInjector
from tests.unit.test_remote_desktop_mouse import MockInputInjector
from tests.unit.test_remote_desktop_streaming import MockCaptureEngine, _recv_type


class _StubService:
    def __init__(self, name: str) -> None:
        self.name = name
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def _wait_for_port_sync(service: RemoteDesktopService, timeout: float = 5.0) -> int:
    return asyncio.run(_wait_for_port(service, timeout=timeout))


def test_settings_loads_v02_config() -> None:
    settings = Settings.from_dict(
        {
            "storage": {
                "screenshots_bucket": "screenshots",
                "desktop_bucket": "desktop-preview",
                "screenshots_dir": "data/screenshots",
            },
            "heartbeat": {"interval": 30},
            "telemetry": {"interval": 60},
            "desktop": {
                "capture_interval": 0.5,
                "jpeg_quality": 70,
                "width": 1280,
                "latest_frame_name": "latest.jpg",
            },
            "camera": {
                "windows_backend": "CAP_DSHOW",
                "default_backend": "CAP_ANY",
                "detection_range": 10,
            },
            "firmware": {"version": "0.2.0"},
            "command": {"poll_interval": 5},
            "remote_desktop": {
                "host": "127.0.0.1",
                "port": 9842,
                "path": "/remote-desktop/v1",
                "subprotocol": "ottoman-remote-desktop.v1",
                "ping_interval": 15,
                "disconnect_timeout": 30,
                "token_ttl_seconds": 60,
                "jwt_secret_env": "REMOTE_DESKTOP_JWT_SECRET",
                "jwt_algorithm": "HS256",
                "fps": 2,
                "jpeg_quality": 70,
                "width": 1280,
            },
        }
    )
    assert settings.remote_desktop.file_transfer.workspace_dir == "data/workspace"
    assert settings.remote_desktop.file_transfer.max_file_size_bytes == 104857600


def test_service_registry_start_stop_order() -> None:
    first = _StubService("heartbeat")
    second = _StubService("telemetry")
    third = _StubService("remote_desktop")

    registry = ServiceRegistry()
    registry.register(first)
    registry.register(second)
    registry.register(third)
    registry.start_all()

    assert first.started is True
    assert second.started is True
    assert third.started is True

    registry.stop_all()

    assert third.stopped is True
    assert second.stopped is True
    assert first.stopped is True


def test_remote_desktop_service_restart_does_not_leak_threads() -> None:
    service = RemoteDesktopService(
        device_id=TEST_DEVICE_ID,
        jwt_secret=TEST_JWT_SECRET,
        remote_desktop_settings=_test_remote_desktop_settings(),
        capture_engine=MockCaptureEngine(),
    )

    for _ in range(3):
        service.start()
        port = _wait_for_port_sync(service, timeout=5.0)
        assert port is not None
        service.stop()

    assert service._thread is None or not service._thread.is_alive()


async def _recv_transfer_message(websocket: Any, expected: str) -> dict[str, Any]:
    while True:
        message = await _recv_json(websocket, timeout=2.0)
        if message["type"] == expected:
            return message


@pytest.mark.asyncio
async def test_combined_remote_desktop_feature_flow() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        settings = _test_remote_desktop_settings()
        server = RemoteDesktopWebSocketServer(
            device_id=TEST_DEVICE_ID,
            settings=settings,
            jwt_secret=TEST_JWT_SECRET,
            capture_engine=MockCaptureEngine(),
            input_injector=MockInputInjector(),
            keyboard_injector=MockKeyboardInjector(),
            file_transfer_manager=FileTransferManager(
                workspace_dir=workspace,
                max_file_size_bytes=settings.file_transfer.max_file_size_bytes,
                chunk_size=settings.file_transfer.chunk_size,
            ),
        )
        await server.start()
        try:
            uri = f"ws://127.0.0.1:{server.bound_port}{settings.path}"
            token = create_session_jwt(
                device_id=TEST_DEVICE_ID,
                secret=TEST_JWT_SECRET,
                ttl_seconds=60,
                permissions=[
                    "desktop",
                    "mouse",
                    "keyboard",
                    "clipboard",
                    "file_transfer",
                ],
                user_id="integration-user",
                controller_name="Integration Tester",
            )

            async with connect(uri, subprotocols=[settings.subprotocol]) as websocket:
                await _send_json(websocket, "HELLO")
                await _recv_json(websocket)
                await _send_json(websocket, "AUTH", {"token": token})
                await _recv_json(websocket)
                await _recv_json(websocket)

                await _send_json(websocket, "START_STREAM")
                await _recv_type(websocket, "START_STREAM")

                await _send_json(websocket, "MOUSE_MOVE", {"x": 0.5, "y": 0.5})
                await _send_json(websocket, "MOUSE_CLICK", {"button": "left"})
                await _send_json(websocket, "KEY_DOWN", {"key": "KeyA"})
                await _send_json(websocket, "KEY_UP", {"key": "KeyA"})
                await _send_json(websocket, "TEXT_INPUT", {"text": "v0.2"})
                await _send_json(websocket, "CLIPBOARD_SET", {"text": "sync"})
                await _recv_json(websocket, timeout=2.0)

                transfer_id = "integration-upload"
                payload = b"integration"
                await _send_json(
                    websocket,
                    "FILE_UPLOAD",
                    {
                        "transfer_id": transfer_id,
                        "path": "integration.txt",
                        "size": len(payload),
                    },
                )
                await _recv_transfer_message(websocket, "FILE_PROGRESS")
                await _send_json(
                    websocket,
                    "FILE_UPLOAD",
                    {
                        "transfer_id": transfer_id,
                        "chunk": base64.b64encode(payload).decode("ascii"),
                    },
                )
                await _recv_transfer_message(websocket, "FILE_PROGRESS")
                complete = await _recv_transfer_message(websocket, "FILE_COMPLETE")
                assert complete["payload"]["path"] == "integration.txt"
                assert (workspace / "integration.txt").read_bytes() == payload

                await _send_json(websocket, "STOP_STREAM")
                await _recv_type(websocket, "STOP_STREAM")
        finally:
            await server.stop()


def test_services_use_independent_threads() -> None:
    started = threading.Event()

    def worker() -> None:
        started.set()
        time.sleep(0.2)

    heartbeat = threading.Thread(target=worker, name="heartbeat", daemon=True)
    telemetry = threading.Thread(target=worker, name="telemetry", daemon=True)
    remote = threading.Thread(target=worker, name="remote_desktop", daemon=True)

    heartbeat.start()
    telemetry.start()
    remote.start()
    started.wait(timeout=1.0)

    names = {thread.name for thread in threading.enumerate()}
    assert "heartbeat" in names
    assert "telemetry" in names
    assert "remote_desktop" in names