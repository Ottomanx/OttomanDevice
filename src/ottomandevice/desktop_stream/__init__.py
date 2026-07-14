import threading

from PIL import Image
from supabase import Client

from ottomandevice.config import settings
from ottomandevice.desktop_stream.capture_engine import CaptureEngine
from ottomandevice.logging import get_logger
from ottomandevice.runtime import get_device_id

STREAM_INTERVAL_SECONDS = settings.desktop.capture_interval
TARGET_WIDTH = settings.desktop.width
JPEG_QUALITY = settings.desktop.jpeg_quality
STORAGE_BUCKET = settings.storage.desktop_bucket
LATEST_FRAME_NAME = settings.desktop.latest_frame_name
logger = get_logger("desktop_stream")


class DesktopStreamService:
    def __init__(
        self,
        supabase: Client,
        interval_seconds: float = STREAM_INTERVAL_SECONDS,
        target_width: int = TARGET_WIDTH,
        jpeg_quality: int = JPEG_QUALITY,
        capture_engine: CaptureEngine | None = None,
    ) -> None:
        self._supabase = supabase
        self._interval_seconds = interval_seconds
        self._capture_engine = capture_engine or CaptureEngine(
            target_width=target_width,
            jpeg_quality=jpeg_quality,
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def capture_engine(self) -> CaptureEngine:
        return self._capture_engine

    def capture_frame(self) -> Image.Image:
        return self._capture_engine.capture_frame()

    def encode_frame(self, image: Image.Image) -> bytes:
        frame_bytes, _, _ = self._capture_engine.encode_frame(image)
        return frame_bytes

    def upload_frame(self, frame_bytes: bytes) -> str:
        device_id = get_device_id()
        storage_path = f"{device_id}/{LATEST_FRAME_NAME}"

        self._supabase.storage.from_(STORAGE_BUCKET).upload(
            storage_path,
            frame_bytes,
            file_options={"content-type": "image/jpeg", "upsert": "true"},
        )

        return self._supabase.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)

    def stream_once(self) -> str:
        image = self.capture_frame()
        frame_bytes = self.encode_frame(image)
        return self.upload_frame(frame_bytes)

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            try:
                self.stream_once()
            except Exception:
                logger.exception("Desktop stream failed")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="desktop-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._interval_seconds + 1)

    def join(self) -> None:
        if self._thread:
            self._thread.join()
