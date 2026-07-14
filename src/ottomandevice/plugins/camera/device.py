from __future__ import annotations

import platform
import threading
from typing import Any, Callable, Protocol

import cv2

from ottomandevice.config import settings

CaptureFactory = Callable[[int, int], Any]


class VideoCaptureProtocol(Protocol):
    """Minimal protocol implemented by OpenCV captures and test doubles."""

    def isOpened(self) -> bool: ...

    def read(self) -> tuple[bool, Any]: ...

    def set(self, prop: int, value: float) -> bool: ...

    def get(self, prop: int) -> float: ...

    def release(self) -> None: ...


def default_capture_factory(device_id: int, backend: int) -> Any:
    """Create a real OpenCV capture device."""
    return cv2.VideoCapture(device_id, backend)


def capture_backend() -> int:
    """Return the platform-specific OpenCV backend constant."""
    if platform.system() == "Windows":
        return int(getattr(cv2, settings.camera.windows_backend))
    return int(getattr(cv2, settings.camera.default_backend))


def backend_name() -> str:
    """Return the configured backend name for telemetry."""
    if platform.system() == "Windows":
        return settings.camera.windows_backend
    return settings.camera.default_backend


class CameraDevice:
    """Thread-safe wrapper around a single camera capture device."""

    def __init__(
        self,
        device_id: int,
        *,
        width: int,
        height: int,
        fps: int,
        capture_factory: CaptureFactory | None = None,
    ) -> None:
        self.device_id = device_id
        self._width = width
        self._height = height
        self._fps = fps
        self._capture_factory = capture_factory or default_capture_factory
        self._capture: Any | None = None
        self._lock = threading.RLock()
        self._backend = backend_name()

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._capture is not None and self._capture.isOpened()

    def open(self) -> bool:
        """Open the camera and apply the configured stream properties."""
        with self._lock:
            if self.is_open:
                return True

            capture = self._capture_factory(self.device_id, capture_backend())
            try:
                if not capture.isOpened():
                    return False
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(self._width))
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(self._height))
                capture.set(cv2.CAP_PROP_FPS, float(self._fps))
                self._capture = capture
                return True
            except Exception:
                capture.release()
                return False

    def close(self) -> None:
        """Release the underlying capture handle."""
        with self._lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None

    def read_frame(self) -> tuple[bool, Any | None]:
        """Read a single frame from the open device."""
        with self._lock:
            if self._capture is None or not self._capture.isOpened():
                return False, None
            return self._capture.read()

    def configure(self, *, width: int, height: int, fps: int) -> None:
        """Update resolution and FPS settings on an open or future session."""
        with self._lock:
            self._width = width
            self._height = height
            self._fps = fps
            if self._capture is not None:
                self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
                self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
                self._capture.set(cv2.CAP_PROP_FPS, float(fps))

    def resolution(self) -> tuple[int, int]:
        """Return the active or configured frame resolution."""
        with self._lock:
            if self._capture is None:
                return self._width, self._height
            width = int(self._capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(self._capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
            return width or self._width, height or self._height

    @property
    def target_fps(self) -> int:
        return self._fps
