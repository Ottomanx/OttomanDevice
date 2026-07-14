import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Callable, cast

from supabase import Client

from ottomandevice.camera import CameraService
from ottomandevice.config import settings
from ottomandevice.logging import get_logger
from ottomandevice.runtime import get_device_id
from ottomandevice.screenshot import ScreenshotService

if TYPE_CHECKING:
    from ottomandevice.heartbeat import HeartbeatService

POLL_INTERVAL_SECONDS = settings.command.poll_interval
COMMAND_STATUS_PENDING = "PENDING"
COMMAND_STATUS_DONE = "DONE"
logger = get_logger("command")


@dataclass(frozen=True)
class DeviceCommand:
    id: str
    device_id: str
    command: str
    status: str


class CommandService:
    def __init__(
        self,
        supabase: Client,
        heartbeat_service: "HeartbeatService | None" = None,
        poll_interval_seconds: int = POLL_INTERVAL_SECONDS,
    ) -> None:
        self._supabase = supabase
        self._heartbeat_service = heartbeat_service
        self._poll_interval_seconds = poll_interval_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._screenshot_service = ScreenshotService(supabase)
        self._handlers: dict[str, Callable[[], None]] = {
            "PING": self._handle_ping,
            "CAMERA_TEST": self._handle_camera_test,
            "HEARTBEAT": self._handle_heartbeat,
            "SCREENSHOT": self._handle_screenshot,
        }

    def _fetch_pending_commands(self) -> list[DeviceCommand]:
        device_id = get_device_id()
        response = (
            self._supabase.table("device_commands")
            .select("id, device_id, command, status")
            .eq("device_id", device_id)
            .eq("status", COMMAND_STATUS_PENDING)
            .order("created_at")
            .execute()
        )

        rows = cast(list[dict[str, Any]], response.data or [])
        return [DeviceCommand(**row) for row in rows]

    def _mark_done(self, command_id: str) -> None:
        self._supabase.table("device_commands").update(
            {
                "status": COMMAND_STATUS_DONE,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", command_id).execute()

    def _handle_ping(self) -> None:
        logger.info("PONG")

    def _handle_camera_test(self) -> None:
        CameraService().run_camera_check()

    def _handle_heartbeat(self) -> None:
        if self._heartbeat_service is None:
            raise RuntimeError("Heartbeat service is not available")

        self._heartbeat_service._send_heartbeat()

    def _handle_screenshot(self) -> None:
        self._screenshot_service.capture_and_upload()
        logger.info("Screenshot uploaded")

    def _execute_command(self, command: DeviceCommand) -> None:
        handler = self._handlers.get(command.command.upper())
        if handler is None:
            return

        handler()
        self._mark_done(command.id)

    def _poll_once(self) -> None:
        for command in self._fetch_pending_commands():
            try:
                self._execute_command(command)
            except Exception:
                logger.exception("Command execution failed")

    def _run(self) -> None:
        while not self._stop_event.wait(self._poll_interval_seconds):
            try:
                self._poll_once()
            except Exception:
                logger.exception("Command poll failed")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="command-service", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._poll_interval_seconds + 1)

    def join(self) -> None:
        if self._thread:
            self._thread.join()
