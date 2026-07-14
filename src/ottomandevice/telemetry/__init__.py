import platform
import socket
import threading
import time
from dataclasses import dataclass

import psutil
from supabase import Client

from ottomandevice.camera import CameraService
from ottomandevice.config import settings
from ottomandevice.logging import get_logger
from ottomandevice.runtime import get_device_id

TELEMETRY_INTERVAL_SECONDS = settings.telemetry.interval
logger = get_logger("telemetry")


@dataclass(frozen=True)
class TelemetryData:
    cpu_usage: float
    ram_usage: float
    disk_usage: float
    hostname: str
    local_ip: str
    system_uptime: int
    camera_available: bool
    python_version: str

    def to_record(self) -> dict[str, float | str | int | bool]:
        return {
            "cpu_usage": self.cpu_usage,
            "ram_usage": self.ram_usage,
            "disk_usage": self.disk_usage,
            "hostname": self.hostname,
            "local_ip": self.local_ip,
            "system_uptime": self.system_uptime,
            "camera_available": self.camera_available,
            "python_version": self.python_version,
        }


class TelemetryService:
    def __init__(
        self,
        supabase: Client,
        interval_seconds: int = TELEMETRY_INTERVAL_SECONDS,
    ) -> None:
        self._supabase = supabase
        self._interval_seconds = interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _disk_usage_percent() -> float:
        path = "C:\\" if platform.system() == "Windows" else "/"
        return float(psutil.disk_usage(path).percent)

    @staticmethod
    def _local_ip() -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return str(sock.getsockname()[0])
        except OSError:
            for addresses in psutil.net_if_addrs().values():
                for address in addresses:
                    if address.family == socket.AF_INET and not address.address.startswith("127."):
                        return str(address.address)
        return "unknown"

    def collect_telemetry(self) -> TelemetryData:
        return TelemetryData(
            cpu_usage=psutil.cpu_percent(interval=0.1),
            ram_usage=float(psutil.virtual_memory().percent),
            disk_usage=self._disk_usage_percent(),
            hostname=socket.gethostname(),
            local_ip=self._local_ip(),
            system_uptime=int(time.time() - psutil.boot_time()),
            camera_available=CameraService().select_first_working_camera() is not None,
            python_version=platform.python_version(),
        )

    def _update_telemetry(self) -> None:
        device_id = get_device_id()
        telemetry = self.collect_telemetry()
        self._supabase.table("devices_enhanced").update(telemetry.to_record()).eq(
            "device_id", device_id
        ).execute()
        logger.info("Telemetry updated")

    def _run(self) -> None:
        while not self._stop_event.wait(self._interval_seconds):
            try:
                self._update_telemetry()
            except Exception:
                logger.exception("Telemetry update failed")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="telemetry", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._interval_seconds + 1)

    def join(self) -> None:
        if self._thread:
            self._thread.join()
