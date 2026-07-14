from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from ottomandevice.plugins.camera.device import CameraDevice

FrameCallback = Callable[[np.ndarray, int], None]


@dataclass(frozen=True)
class FrameResult:
    """Result of a single-frame capture attempt."""

    success: bool
    frame: Any | None
    frame_number: int
    width: int
    height: int
    dropped: bool = False
    streaming: bool = False


class CameraCapture:
    """Single-frame and continuous capture helpers for a camera device."""

    def __init__(
        self,
        device: CameraDevice,
        *,
        dropped_frame_multiplier: float = 2.0,
    ) -> None:
        self._device = device
        self._dropped_frame_multiplier = dropped_frame_multiplier
        self._lock = threading.RLock()
        self._streaming = False
        self._stream_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._frame_count = 0
        self._dropped_frames = 0
        self._last_frame_at: float | None = None
        self._latest_frame: Any | None = None
        self._frame_callback: FrameCallback | None = None
        self._on_frame_event: Callable[[FrameResult], None] | None = None

    @property
    def frame_count(self) -> int:
        with self._lock:
            return self._frame_count

    @property
    def dropped_frames(self) -> int:
        with self._lock:
            return self._dropped_frames

    @property
    def is_streaming(self) -> bool:
        with self._lock:
            return self._streaming

    @property
    def latest_frame(self) -> Any | None:
        with self._lock:
            return self._latest_frame

    def set_frame_callback(self, callback: FrameCallback | None) -> None:
        with self._lock:
            self._frame_callback = callback

    def set_frame_event_handler(self, handler: Callable[[FrameResult], None] | None) -> None:
        with self._lock:
            self._on_frame_event = handler

    def capture_single(self) -> FrameResult:
        """Capture one frame from the device."""
        success, frame = self._device.read_frame()
        dropped = self._evaluate_drop(success)
        result = self._build_result(success, frame, dropped=dropped, streaming=False)
        self._record_frame(result)
        return result

    def start_stream(self) -> None:
        """Start a background thread that continuously reads frames."""
        with self._lock:
            if self._streaming:
                return
            self._stop_event.clear()
            self._streaming = True
            self._stream_thread = threading.Thread(
                target=self._stream_loop,
                name=f"camera-stream-{self._device.device_id}",
                daemon=True,
            )
            self._stream_thread.start()

    def stop_stream(self) -> None:
        """Stop the streaming thread and wait for it to exit."""
        with self._lock:
            if not self._streaming:
                return
            self._stop_event.set()
            thread = self._stream_thread
            self._streaming = False

        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)

        with self._lock:
            self._stream_thread = None

    def reset_counters(self) -> None:
        with self._lock:
            self._frame_count = 0
            self._dropped_frames = 0
            self._last_frame_at = None

    def _stream_loop(self) -> None:
        target_interval = 1.0 / max(self._device.target_fps, 1)
        while not self._stop_event.is_set():
            loop_start = time.monotonic()
            success, frame = self._device.read_frame()
            dropped = self._evaluate_drop(success)
            result = self._build_result(success, frame, dropped=dropped, streaming=True)
            self._record_frame(result)

            elapsed = time.monotonic() - loop_start
            sleep_for = max(0.0, target_interval - elapsed)
            if self._stop_event.wait(sleep_for):
                break

    def _evaluate_drop(self, success: bool) -> bool:
        if not success:
            return True

        now = time.monotonic()
        target_interval = 1.0 / max(self._device.target_fps, 1)
        threshold = target_interval * self._dropped_frame_multiplier

        with self._lock:
            if self._last_frame_at is not None and (now - self._last_frame_at) > threshold:
                self._dropped_frames += 1
                self._last_frame_at = now
                return True
            self._last_frame_at = now
            return False

    def _build_result(
        self,
        success: bool,
        frame: Any | None,
        *,
        dropped: bool,
        streaming: bool,
    ) -> FrameResult:
        width, height = self._device.resolution()
        if success and frame is not None and hasattr(frame, "shape") and len(frame.shape) >= 2:
            height, width = int(frame.shape[0]), int(frame.shape[1])

        with self._lock:
            frame_number = self._frame_count + 1

        return FrameResult(
            success=success,
            frame=frame,
            frame_number=frame_number,
            width=width,
            height=height,
            dropped=dropped,
            streaming=streaming,
        )

    def _record_frame(self, result: FrameResult) -> None:
        handler: Callable[[FrameResult], None] | None
        callback: FrameCallback | None
        with self._lock:
            if result.success and result.frame is not None:
                self._frame_count += 1
                self._latest_frame = result.frame
            elif result.dropped:
                self._dropped_frames += 1
            handler = self._on_frame_event
            callback = self._frame_callback
            frame = self._latest_frame
            frame_number = self._frame_count

        if handler is not None:
            handler(result)
        if callback is not None and result.success and frame is not None:
            callback(frame, frame_number)
