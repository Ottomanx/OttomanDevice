from __future__ import annotations

import threading
import time
from typing import Any, Callable

from ottomandevice.config import settings
from ottomandevice.core.event_bus import (
    CameraClosed,
    CameraDetected,
    CameraDisconnected,
    CameraError,
    CameraFrameCaptured,
    CameraOpened,
    CameraReconnected,
    EventBus,
)
from ottomandevice.core.health import HealthMonitor
from ottomandevice.plugins.camera.capture import CameraCapture, FrameResult
from ottomandevice.plugins.camera.device import CameraDevice, CaptureFactory, backend_name, capture_backend
from ottomandevice.plugins.camera.health import CameraHealth

HOTPLUG_INTERVAL_SECONDS = 3.0
RECONNECT_BASE_DELAY_SECONDS = 1.0
RECONNECT_MAX_DELAY_SECONDS = 30.0


class CameraManager:
    """Orchestrates camera discovery, capture, health, and hot-plug handling."""

    _instance: CameraManager | None = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        capture_factory: CaptureFactory | None = None,
        hotplug_interval: float = HOTPLUG_INTERVAL_SECONDS,
    ) -> None:
        self._event_bus = event_bus or EventBus.get_instance()
        self._capture_factory = capture_factory
        self._hotplug_interval = hotplug_interval
        self._lock = threading.RLock()
        self._device: CameraDevice | None = None
        self._capture: CameraCapture | None = None
        self._health = CameraHealth(fps_target=settings.camera.fps)
        self._discovered: list[int] = []
        self._selected_device: int | str = settings.camera.device
        self._hotplug_thread: threading.Thread | None = None
        self._hotplug_stop = threading.Event()
        self._reconnect_delay = RECONNECT_BASE_DELAY_SECONDS
        self._health_supplier_registered = False

    @classmethod
    def get_instance(
        cls,
        *,
        event_bus: EventBus | None = None,
        capture_factory: CaptureFactory | None = None,
    ) -> CameraManager:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(event_bus=event_bus, capture_factory=capture_factory)
            return cls._instance

    @classmethod
    def get_instance_optional(cls) -> CameraManager | None:
        with cls._instance_lock:
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    @property
    def health(self) -> CameraHealth:
        return self._health

    @property
    def discovered_devices(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(self._discovered)

    @property
    def active_device_id(self) -> int | None:
        with self._lock:
            return self._device.device_id if self._device is not None else None

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._device is not None and self._device.is_open

    @property
    def is_streaming(self) -> bool:
        with self._lock:
            return self._capture is not None and self._capture.is_streaming

    def register_health_monitor(self) -> None:
        """Expose camera metrics through the runtime health monitor."""
        if self._health_supplier_registered:
            return
        HealthMonitor.register_supplier(self._health.to_metrics)
        self._health_supplier_registered = True

    def unregister_health_monitor(self) -> None:
        if not self._health_supplier_registered:
            return
        HealthMonitor.unregister_supplier(self._health.to_metrics)
        self._health_supplier_registered = False

    def discover(self) -> list[int]:
        """Probe configured indices and publish detection events."""
        available: list[int] = []
        backend = capture_backend()
        detection_range = settings.camera.detection_range

        for index in range(detection_range):
            from ottomandevice.plugins.camera.device import default_capture_factory

            factory = self._capture_factory or default_capture_factory
            probe = factory(index, backend)
            try:
                if not probe.isOpened():
                    continue
                success, frame = probe.read()
                if not success or frame is None:
                    continue
                available.append(index)
                height, width = frame.shape[:2]
                self._publish(
                    CameraDetected(
                        device_id=index,
                        width=int(width),
                        height=int(height),
                        backend=backend_name(),
                    )
                )
            finally:
                probe.release()

        with self._lock:
            previous = set(self._discovered)
            current = set(available)
            self._discovered = available

            active_id = self._device.device_id if self._device is not None else None
            if active_id is not None and active_id not in current:
                self._handle_disconnect(f"Camera index {active_id} no longer available")

            for device_id in sorted(current - previous):
                if active_id is None and settings.camera.device == "auto":
                    continue

        return available

    def select_device(self, device: int | str) -> None:
        """Select a camera by numeric id or the string 'auto'."""
        with self._lock:
            self._selected_device = device

    def open(self, device: int | str | None = None) -> bool:
        """Open the selected or provided camera device."""
        if not settings.camera.enabled:
            return False

        target = device if device is not None else self._selected_device
        device_id = self._resolve_device_id(target)
        if device_id is None:
            return False

        if self.is_open and self.active_device_id == device_id:
            return True

        self.close()
        camera = CameraDevice(
            device_id,
            width=settings.camera.width,
            height=settings.camera.height,
            fps=settings.camera.fps,
            capture_factory=self._capture_factory,
        )
        if not camera.open():
            self._publish_error(device_id, "open", "Unable to open camera device")
            return False

        capture = CameraCapture(camera)
        capture.set_frame_event_handler(self._on_frame_captured)

        with self._lock:
            self._device = camera
            self._capture = capture
            self._reconnect_delay = RECONNECT_BASE_DELAY_SECONDS

        width, height = camera.resolution()
        self._health.set_target_fps(settings.camera.fps)
        self._health.set_device(device_id, connected=True)
        self._health.record_reconnect(device_id)
        self._publish(
            CameraOpened(
                device_id=device_id,
                backend=camera.backend,
                width=width,
                height=height,
            )
        )
        return True

    def close(self) -> None:
        """Close the active camera and stop streaming."""
        with self._lock:
            device = self._device
            capture = self._capture
            self._device = None
            self._capture = None

        if capture is not None:
            capture.stop_stream()
        if device is not None:
            device_id = device.device_id
            device.close()
            self._health.set_device(device_id, connected=False)
            self._health.record_disconnect()
            self._publish(CameraClosed(device_id=device_id))

    def capture_frame(self) -> FrameResult:
        """Capture a single frame from the open camera."""
        with self._lock:
            capture = self._capture
            device_id = self._device.device_id if self._device is not None else -1

        if capture is None:
            result = FrameResult(False, None, 0, 0, 0)
            self._publish_error(device_id, "capture", "Camera is not open")
            return result

        result = capture.capture_single()
        if not result.success:
            self._handle_disconnect("Frame capture failed")
        else:
            self._health.record_frame(success=True, dropped=result.dropped)
            self._sync_health_counters(capture)
        return result

    def start_stream(self) -> None:
        with self._lock:
            capture = self._capture
        if capture is None:
            self._publish_error(-1, "stream", "Camera is not open")
            return
        capture.start_stream()

    def stop_stream(self) -> None:
        with self._lock:
            capture = self._capture
        if capture is not None:
            capture.stop_stream()

    def configure(self, *, width: int, height: int, fps: int) -> None:
        with self._lock:
            device = self._device
        if device is not None:
            device.configure(width=width, height=height, fps=fps)
            self._health.set_target_fps(fps)

    def start_hotplug_monitor(self) -> None:
        with self._lock:
            if self._hotplug_thread is not None and self._hotplug_thread.is_alive():
                return
            self._hotplug_stop.clear()
            self._hotplug_thread = threading.Thread(
                target=self._hotplug_loop,
                name="camera-hotplug",
                daemon=True,
            )
            self._hotplug_thread.start()

    def stop_hotplug_monitor(self) -> None:
        self._hotplug_stop.set()
        with self._lock:
            thread = self._hotplug_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._hotplug_interval + 2)
        with self._lock:
            self._hotplug_thread = None

    def attempt_reconnect(self) -> bool:
        """Try to reopen the last selected device after a disconnect."""
        device = self._selected_device
        if self.open(device):
            device_id = self.active_device_id
            if device_id is not None:
                self._publish(CameraReconnected(device_id=device_id))
            self._reconnect_delay = RECONNECT_BASE_DELAY_SECONDS
            return True
        self._reconnect_delay = min(
            self._reconnect_delay * 2,
            RECONNECT_MAX_DELAY_SECONDS,
        )
        return False

    def health_report(self) -> dict[str, Any]:
        with self._lock:
            capture = self._capture
        if capture is not None:
            self._sync_health_counters(capture)
        return self._health.to_cloud_dict()

    def shutdown(self) -> None:
        self.stop_hotplug_monitor()
        self.stop_stream()
        self.close()
        self.unregister_health_monitor()

    def _hotplug_loop(self) -> None:
        while not self._hotplug_stop.wait(self._hotplug_interval):
            try:
                self.discover()
                if not self.is_open and settings.camera.enabled:
                    if self._selected_device == "auto" and self._discovered:
                        self.open("auto")
                    elif self._should_reconnect():
                        time.sleep(self._reconnect_delay)
                        self.attempt_reconnect()
            except Exception as exc:
                self._publish_error(self.active_device_id or -1, "hotplug", str(exc))

    def _should_reconnect(self) -> bool:
        with self._lock:
            if self._selected_device == "auto":
                return bool(self._discovered)
            if isinstance(self._selected_device, int):
                return self._selected_device in self._discovered
            if str(self._selected_device).isdigit():
                return int(self._selected_device) in self._discovered
            return False

    def _resolve_device_id(self, target: int | str) -> int | None:
        if isinstance(target, int):
            return target
        if str(target).isdigit():
            return int(target)
        if str(target) == "auto":
            if not self._discovered:
                self.discover()
            return self._discovered[0] if self._discovered else None
        return None

    def _handle_disconnect(self, reason: str) -> None:
        device_id = self.active_device_id
        self.close()
        if device_id is not None:
            self._publish(CameraDisconnected(device_id=device_id, reason=reason))

    def _on_frame_captured(self, result: FrameResult) -> None:
        device_id = self.active_device_id or -1
        if not result.success:
            self._health.record_frame(success=False, dropped=True)
            self._handle_disconnect("Streaming frame read failed")
            return

        self._health.record_frame(success=True, dropped=result.dropped)
        with self._lock:
            capture = self._capture
        if capture is not None:
            self._sync_health_counters(capture)

        self._publish(
            CameraFrameCaptured(
                device_id=device_id,
                frame_number=result.frame_number,
                width=result.width,
                height=result.height,
                streaming=result.streaming,
            )
        )

    def _sync_health_counters(self, capture: CameraCapture) -> None:
        self._health.sync_capture_stats(
            frames_captured=capture.frame_count,
            frames_dropped=capture.dropped_frames,
        )

    def _publish(self, event: Any) -> None:
        self._event_bus.publish(event)

    def _publish_error(self, device_id: int, operation: str, error: str) -> None:
        self._health.record_error(error)
        self._publish(CameraError(device_id=device_id, operation=operation, error=error))
