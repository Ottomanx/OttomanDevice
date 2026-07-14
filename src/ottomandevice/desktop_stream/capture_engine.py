from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageGrab

if TYPE_CHECKING:
    from ottomandevice.remote_desktop.monitor.models import MonitorInfo


@dataclass(frozen=True)
class CaptureRegion:
    left: int
    top: int
    width: int
    height: int

    @property
    def bbox(self) -> tuple[int, int, int, int]:
        return (
            self.left,
            self.top,
            self.left + self.width,
            self.top + self.height,
        )


class CaptureEngine:
    def __init__(self, target_width: int, jpeg_quality: int) -> None:
        self._target_width = target_width
        self._jpeg_quality = jpeg_quality
        self._buffer = BytesIO()
        self._active_region: CaptureRegion | None = None

    def set_active_monitor(self, monitor: MonitorInfo | None) -> None:
        if monitor is None:
            self._active_region = None
            return
        self._active_region = CaptureRegion(
            left=monitor.x,
            top=monitor.y,
            width=monitor.width,
            height=monitor.height,
        )

    def capture_frame(self) -> Image.Image:
        if self._active_region is not None:
            return ImageGrab.grab(bbox=self._active_region.bbox)
        return ImageGrab.grab()

    def encode_frame(self, image: Image.Image) -> tuple[bytes, int, int]:
        width, height = image.size
        new_height = max(1, int(height * self._target_width / width))
        resized = image.resize((self._target_width, new_height), Image.Resampling.LANCZOS)

        self._buffer.seek(0)
        self._buffer.truncate(0)
        resized.convert("RGB").save(
            self._buffer,
            format="JPEG",
            quality=self._jpeg_quality,
        )
        return self._buffer.getvalue(), self._target_width, new_height

    def capture_and_encode(self) -> tuple[bytes, int, int]:
        return self.encode_frame(self.capture_frame())
