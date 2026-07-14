from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from ottomandevice.core.health import MetricValue


@dataclass(frozen=True)
class CameraHealthSnapshot:
    """Point-in-time camera health state."""

    status: str
    connected: bool
    device_id: int | None
    fps_target: int
    fps_actual: float
    frames_captured: int
    frames_dropped: int
    last_error: str | None
    last_frame_age_seconds: float | None


class CameraHealth:
    """Tracks camera connectivity, throughput, and error conditions."""

    def __init__(self, *, fps_target: int = 30) -> None:
        self._lock = threading.RLock()
        self._fps_target = fps_target
        self._connected = False
        self._device_id: int | None = None
        self._frames_captured = 0
        self._frames_dropped = 0
        self._last_error: str | None = None
        self._last_frame_at: float | None = None
        self._fps_window_start = time.monotonic()
        self._fps_window_frames = 0
        self._fps_actual = 0.0

    def set_target_fps(self, fps: int) -> None:
        with self._lock:
            self._fps_target = max(fps, 1)

    def set_device(self, device_id: int | None, *, connected: bool) -> None:
        with self._lock:
            self._device_id = device_id
            self._connected = connected

    def record_frame(self, *, success: bool, dropped: bool = False) -> None:
        with self._lock:
            if success:
                self._frames_captured += 1
                self._last_frame_at = time.monotonic()
                self._fps_window_frames += 1
                elapsed = self._last_frame_at - self._fps_window_start
                if elapsed >= 1.0:
                    self._fps_actual = self._fps_window_frames / elapsed
                    self._fps_window_start = self._last_frame_at
                    self._fps_window_frames = 0
            if dropped:
                self._frames_dropped += 1

    def record_disconnect(self) -> None:
        with self._lock:
            self._connected = False

    def record_reconnect(self, device_id: int) -> None:
        with self._lock:
            self._connected = True
            self._device_id = device_id
            self._last_error = None

    def record_error(self, error: str) -> None:
        with self._lock:
            self._last_error = error

    def sync_capture_stats(self, *, frames_captured: int, frames_dropped: int) -> None:
        with self._lock:
            self._frames_captured = frames_captured
            self._frames_dropped = frames_dropped

    def snapshot(self) -> CameraHealthSnapshot:
        with self._lock:
            last_frame_age = None
            if self._last_frame_at is not None:
                last_frame_age = max(0.0, time.monotonic() - self._last_frame_at)

            status = self._resolve_status(last_frame_age)
            return CameraHealthSnapshot(
                status=status,
                connected=self._connected,
                device_id=self._device_id,
                fps_target=self._fps_target,
                fps_actual=round(self._fps_actual, 2),
                frames_captured=self._frames_captured,
                frames_dropped=self._frames_dropped,
                last_error=self._last_error,
                last_frame_age_seconds=last_frame_age,
            )

    def to_metrics(self) -> tuple[tuple[MetricValue, ...], dict[str, Any]]:
        snap = self.snapshot()
        metrics: list[MetricValue] = [
            MetricValue("camera_fps_actual", snap.fps_actual, "fps", _metric_status(snap.status)),
            MetricValue(
                "camera_frames_dropped",
                float(snap.frames_dropped),
                "frames",
                "warn" if snap.frames_dropped > 0 else "ok",
            ),
        ]
        details = {
            "camera_status": snap.status,
            "camera_connected": snap.connected,
            "camera_device_id": snap.device_id,
            "camera_fps_target": snap.fps_target,
            "camera_frames_captured": snap.frames_captured,
            "camera_last_error": snap.last_error,
        }
        return tuple(metrics), details

    def to_cloud_dict(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "status": snap.status,
            "connected": snap.connected,
            "device_id": snap.device_id,
            "fps_target": snap.fps_target,
            "fps_actual": snap.fps_actual,
            "frames_captured": snap.frames_captured,
            "frames_dropped": snap.frames_dropped,
            "last_error": snap.last_error,
        }

    def _resolve_status(self, last_frame_age: float | None) -> str:
        if not self._connected:
            return "disconnected"
        if self._last_error:
            return "error"
        if self._frames_dropped > 0:
            return "warn"
        if last_frame_age is not None and last_frame_age > (2.0 / max(self._fps_target, 1)):
            return "warn"
        return "ok"


def _metric_status(status: str) -> str:
    if status in {"error", "disconnected"}:
        return "warn"
    if status == "warn":
        return "warn"
    return "ok"
