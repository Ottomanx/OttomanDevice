from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageGrab


class CaptureEngine:
    def __init__(self, target_width: int, jpeg_quality: int) -> None:
        self._target_width = target_width
        self._jpeg_quality = jpeg_quality
        self._buffer = BytesIO()

    def capture_frame(self) -> Image.Image:
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