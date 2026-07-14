from datetime import datetime
from pathlib import Path

from PIL import ImageGrab
from supabase import Client

from ottomandevice.config import settings
from ottomandevice.runtime import PROJECT_ROOT, get_device_id

SCREENSHOTS_DIR = PROJECT_ROOT / settings.storage.screenshots_dir
STORAGE_BUCKET = settings.storage.screenshots_bucket


class ScreenshotService:
    def __init__(
        self,
        supabase: Client,
        screenshots_dir: Path = SCREENSHOTS_DIR,
    ) -> None:
        self._supabase = supabase
        self._screenshots_dir = screenshots_dir

    @staticmethod
    def _build_filename() -> str:
        return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"

    def capture(self) -> Path:
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)

        filename = self._build_filename()
        output_path = self._screenshots_dir / filename

        image = ImageGrab.grab()
        image.save(output_path, format="PNG")

        return output_path

    def upload(self, local_path: Path) -> str:
        device_id = get_device_id()
        storage_path = f"{device_id}/{local_path.name}"

        file_bytes = local_path.read_bytes()
        self._supabase.storage.from_(STORAGE_BUCKET).upload(
            storage_path,
            file_bytes,
            file_options={"content-type": "image/png", "upsert": "true"},
        )

        return self._supabase.storage.from_(STORAGE_BUCKET).get_public_url(storage_path)

    def capture_and_upload(self) -> str:
        local_path = self.capture()
        return self.upload(local_path)
