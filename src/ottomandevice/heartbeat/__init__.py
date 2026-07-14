import threading
from datetime import datetime, timezone

from supabase import Client

from ottomandevice.config import settings
from ottomandevice.logging import get_logger
from ottomandevice.runtime import get_device_id

HEARTBEAT_INTERVAL_SECONDS = settings.heartbeat.interval
logger = get_logger("heartbeat")


class HeartbeatService:
    def __init__(
        self, supabase: Client, interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS
    ) -> None:
        self._supabase = supabase
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def _send_heartbeat(self) -> None:
        device_id = get_device_id()
        self._supabase.table("devices_enhanced").update(
            {
                "status": "ONLINE",
                "last_online_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("device_id", device_id).execute()
        logger.info("Heartbeat sent")

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            try:
                self._send_heartbeat()
            except Exception:
                logger.exception("Heartbeat failed")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)
        self._thread.start()
        try:
            self._send_heartbeat()
        except Exception:
            logger.exception("Initial heartbeat failed")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._interval_seconds + 1)

    def join(self) -> None:
        if self._thread:
            self._thread.join()
