import platform
from dataclasses import dataclass
from typing import Any

import cv2

from ottomandevice.config import settings
from ottomandevice.logging import get_logger

MAX_CAMERA_PROBE_INDEX = settings.camera.detection_range
logger = get_logger("camera")


@dataclass(frozen=True)
class CameraInfo:
    index: int
    width: int
    height: int


class CameraService:
    def __init__(self, max_probe_index: int = MAX_CAMERA_PROBE_INDEX) -> None:
        self._max_probe_index = max_probe_index

    @staticmethod
    def _capture_backend() -> int:
        if platform.system() == "Windows":
            return int(getattr(cv2, settings.camera.windows_backend))
        return int(getattr(cv2, settings.camera.default_backend))

    def detect_available_cameras(self) -> list[int]:
        available: list[int] = []
        backend = self._capture_backend()

        for index in range(self._max_probe_index):
            capture = cv2.VideoCapture(index, backend)
            try:
                if capture.isOpened():
                    available.append(index)
            finally:
                capture.release()

        return available

    def select_first_working_camera(self) -> int | None:
        backend = self._capture_backend()

        for index in self.detect_available_cameras():
            capture = cv2.VideoCapture(index, backend)
            try:
                if not capture.isOpened():
                    continue

                success, frame = capture.read()
                if success and frame is not None:
                    return index
            finally:
                capture.release()

        return None

    def capture_test_frame(self, index: int) -> tuple[bool, Any]:
        capture = cv2.VideoCapture(index, self._capture_backend())
        try:
            if not capture.isOpened():
                return False, None

            return capture.read()
        finally:
            capture.release()

    def run_camera_check(self) -> CameraInfo | None:
        camera_index = self.select_first_working_camera()
        if camera_index is None:
            logger.info("Camera: not detected")
            return None

        success, frame = self.capture_test_frame(camera_index)
        if not success or frame is None:
            logger.info("Camera: not detected")
            return None

        height, width = frame.shape[:2]
        logger.info("Camera: index %s, %sx%s", camera_index, width, height)

        return CameraInfo(index=camera_index, width=width, height=height)
