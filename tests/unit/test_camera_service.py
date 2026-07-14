from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from ottomandevice.config.settings import CameraSettings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.core.health import HealthMonitor
from ottomandevice.core.plugin_manager import PluginManager
from ottomandevice.plugins.camera.capture import CameraCapture
from ottomandevice.plugins.camera.device import CameraDevice
from ottomandevice.plugins.camera.health import CameraHealth
from ottomandevice.plugins.camera.manager import CameraManager
from ottomandevice.plugins.camera.plugin import OttomanCameraPlugin


class MockVideoCapture:
    """OpenCV VideoCapture test double."""

    _registry: dict[int, "MockVideoCapture"] = {}
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FPS = 5

    def __init__(self, device_id: int, backend: int) -> None:
        self.device_id = device_id
        self.backend = backend
        self._opened = device_id in {0, 1}
        self._width = 1280
        self._height = 720
        self._fps = 30
        MockVideoCapture._registry[device_id] = self

    def isOpened(self) -> bool:
        return self._opened

    def read(self) -> tuple[bool, Any | None]:
        if not self._opened:
            return False, None
        frame = np.zeros((self._height, self._width, 3), dtype=np.uint8)
        return True, frame

    def set(self, prop: int, value: float) -> bool:
        if prop == self.CAP_PROP_FRAME_WIDTH:
            self._width = int(value)
        elif prop == self.CAP_PROP_FRAME_HEIGHT:
            self._height = int(value)
        elif prop == self.CAP_PROP_FPS:
            self._fps = int(value)
        return True

    def get(self, prop: int) -> float:
        if prop == self.CAP_PROP_FRAME_WIDTH:
            return float(self._width)
        if prop == self.CAP_PROP_FRAME_HEIGHT:
            return float(self._height)
        if prop == self.CAP_PROP_FPS:
            return float(self._fps)
        return 0.0

    def release(self) -> None:
        self._opened = False


def mock_capture_factory(device_id: int, backend: int) -> MockVideoCapture:
    return MockVideoCapture(device_id, backend)


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=200)
    yield event_bus
    event_bus.shutdown()


@pytest.fixture(autouse=True)
def reset_singletons() -> None:
    CameraManager.reset_instance()
    HealthMonitor.clear_suppliers()
    PluginManager.reset_instance()
    MockVideoCapture._registry.clear()
    yield
    CameraManager.reset_instance()
    HealthMonitor.clear_suppliers()
    PluginManager.reset_instance()
    MockVideoCapture._registry.clear()


@pytest.fixture
def camera_settings() -> CameraSettings:
    return CameraSettings(
        enabled=True,
        device="auto",
        width=1280,
        height=720,
        fps=30,
        windows_backend="CAP_DSHOW",
        default_backend="CAP_ANY",
        detection_range=4,
    )


@pytest.fixture
def patched_settings(camera_settings: CameraSettings):
    patches = [
        patch("ottomandevice.plugins.camera.manager.settings"),
        patch("ottomandevice.plugins.camera.device.settings"),
        patch("ottomandevice.plugins.camera.plugin.settings"),
    ]
    mocks = [item.start() for item in patches]
    for mock in mocks:
        mock.camera = camera_settings
    yield camera_settings
    for item in patches:
        item.stop()


def _manager(bus: EventBus) -> CameraManager:
    return CameraManager(event_bus=bus, capture_factory=mock_capture_factory, hotplug_interval=0.05)


def test_discover_cameras_publishes_detected_events(bus: EventBus, patched_settings) -> None:
    events: list[str] = []
    bus.subscribe("CameraDetected", lambda event: events.append(event.event_type))

    manager = _manager(bus)
    discovered = manager.discover()

    assert discovered == [0, 1]
    assert events.count("CameraDetected") == 2


def test_auto_select_default_camera(bus: EventBus, patched_settings) -> None:
    manager = _manager(bus)
    manager.discover()

    assert manager.open("auto") is True
    assert manager.active_device_id == 0


def test_manual_camera_selection_by_id(bus: EventBus, patched_settings) -> None:
    manager = _manager(bus)
    manager.discover()

    assert manager.open(1) is True
    assert manager.active_device_id == 1


def test_open_and_close_camera(bus: EventBus, patched_settings) -> None:
    events: list[str] = []
    bus.subscribe("CameraOpened", lambda event: events.append(event.event_type))
    bus.subscribe("CameraClosed", lambda event: events.append(event.event_type))

    manager = _manager(bus)
    manager.discover()
    assert manager.open(0) is True
    assert manager.is_open is True

    manager.close()
    assert manager.is_open is False
    assert events == ["CameraOpened", "CameraClosed"]


def test_capture_single_frame(bus: EventBus, patched_settings) -> None:
    events: list[str] = []
    bus.subscribe("CameraFrameCaptured", lambda event: events.append(event.event_type))

    manager = _manager(bus)
    manager.discover()
    manager.open(0)

    result = manager.capture_frame()

    assert result.success is True
    assert result.frame is not None
    assert events == ["CameraFrameCaptured"]


def test_continuous_streaming_mode(bus: EventBus, patched_settings) -> None:
    manager = _manager(bus)
    manager.discover()
    manager.open(0)
    manager.start_stream()

    time.sleep(0.15)
    manager.stop_stream()

    assert manager.health.snapshot().frames_captured >= 1


def test_resolution_and_fps_configuration(patched_settings) -> None:
    device = CameraDevice(0, width=640, height=480, fps=15, capture_factory=mock_capture_factory)
    assert device.open() is True

    device.configure(width=1920, height=1080, fps=24)
    capture = MockVideoCapture._registry[0]

    assert capture._width == 1920
    assert capture._height == 1080
    assert capture._fps == 24


def test_reconnect_after_disconnect(bus: EventBus, patched_settings) -> None:
    events: list[str] = []
    bus.subscribe("CameraDisconnected", lambda event: events.append(event.event_type))
    bus.subscribe("CameraReconnected", lambda event: events.append(event.event_type))

    manager = _manager(bus)
    manager.discover()
    manager.open(0)

    MockVideoCapture._registry[0]._opened = False
    result = manager.capture_frame()
    assert result.success is False
    assert "CameraDisconnected" in events

    MockVideoCapture._registry[0]._opened = True
    assert manager.attempt_reconnect() is True
    assert "CameraReconnected" in events


def test_health_monitoring_reports_metrics(bus: EventBus, patched_settings) -> None:
    manager = _manager(bus)
    manager.register_health_monitor()
    manager.discover()
    manager.open(0)
    manager.capture_frame()

    report = HealthMonitor().collect()

    metric_names = {metric.name for metric in report.metrics}
    assert "camera_fps_actual" in metric_names
    assert "camera_frames_dropped" in metric_names
    assert report.details.get("camera_connected") is True


def test_dropped_frame_detection(patched_settings) -> None:
    device = CameraDevice(0, width=640, height=480, fps=100, capture_factory=mock_capture_factory)
    device.open()
    capture = CameraCapture(device, dropped_frame_multiplier=1.1)

    capture.capture_single()
    time.sleep(0.03)
    result = capture.capture_single()

    assert result.dropped is True
    assert capture.dropped_frames >= 1


def test_camera_error_event_on_invalid_open(bus: EventBus, patched_settings) -> None:
    operations: list[str] = []
    bus.subscribe("CameraError", lambda event: operations.append(event.payload.get("operation")))

    manager = _manager(bus)
    assert manager.open(99) is False
    assert operations == ["open"]


def test_runtime_starts_without_camera(bus: EventBus, patched_settings) -> None:
    plugin = OttomanCameraPlugin()
    plugin.install()
    plugin.initialize()

    with patch.object(CameraManager, "discover", return_value=[]):
        with patch.object(CameraManager, "open", return_value=False):
            plugin.start()

    assert plugin.manager is not None
    assert plugin.manager.is_open is False

    plugin.stop()
    plugin.uninstall()


def test_camera_plugin_metadata() -> None:
    plugin = OttomanCameraPlugin()
    assert plugin.metadata.id == "camera"
    assert plugin.metadata.name == "Camera Service"


def test_hot_plug_monitor_runs_discovery(bus: EventBus, patched_settings) -> None:
    manager = _manager(bus)
    manager.discover()
    manager.start_hotplug_monitor()
    time.sleep(0.12)
    manager.stop_hotplug_monitor()
    assert manager.discovered_devices == (0, 1)


def test_camera_health_snapshot() -> None:
    health = CameraHealth(fps_target=30)
    health.set_device(0, connected=True)
    health.record_frame(success=True)

    snapshot = health.snapshot()
    assert snapshot.status == "ok"
    assert snapshot.connected is True
    assert snapshot.device_id == 0


def test_cloud_health_report(bus: EventBus, patched_settings) -> None:
    manager = _manager(bus)
    manager.discover()
    manager.open(0)
    manager.capture_frame()

    report = manager.health_report()
    assert report["connected"] is True
    assert report["device_id"] == 0
    assert report["frames_captured"] >= 1


def test_camera_disabled_skips_open(bus: EventBus, camera_settings: CameraSettings) -> None:
    disabled = CameraSettings(
        enabled=False,
        device=camera_settings.device,
        width=camera_settings.width,
        height=camera_settings.height,
        fps=camera_settings.fps,
        windows_backend=camera_settings.windows_backend,
        default_backend=camera_settings.default_backend,
        detection_range=camera_settings.detection_range,
    )
    with patch("ottomandevice.plugins.camera.manager.settings") as mock_settings:
        mock_settings.camera = disabled
        manager = _manager(bus)
        manager.discover()
        assert manager.open("auto") is False
