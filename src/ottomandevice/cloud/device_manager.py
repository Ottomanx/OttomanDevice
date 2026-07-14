from __future__ import annotations

import asyncio
import logging
import platform
import socket
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Deque, cast

import psutil
from supabase import Client

from ottomandevice.core.event_bus import (
    EventBus,
    HeartbeatReceived,
    RemoteCommandExecuted,
    RemoteCommandFailed,
    RemoteCommandReceived,
)
from ottomandevice.core.logger import get_logger
from ottomandevice.device.profile import APPLICATION_VERSION, RUNTIME_VERSION

HEARTBEAT_INTERVAL_SECONDS = 30
COMMAND_POLL_INTERVAL_SECONDS = 5
INITIAL_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 300.0
COMMAND_TTL_SECONDS = 3600
COMMAND_STATUS_PENDING = "PENDING"
COMMAND_STATUS_DONE = "DONE"
COMMAND_STATUS_FAILED = "FAILED"
ONLINE_STATUS = "ONLINE"


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"


@dataclass(frozen=True)
class RemoteCommandRecord:
    """Cloud command row fetched from Supabase."""

    id: str
    device_id: str
    command: str
    status: str
    created_at: str | None = None


@dataclass(frozen=True)
class HeartbeatMetrics:
    """Heartbeat payload sent to the cloud backend."""

    device_uuid: str
    online_status: str
    uptime: int
    cpu: float
    ram: float
    disk: float
    network: dict[str, int]
    runtime_version: str
    application_version: str

    def to_cloud_record(self) -> dict[str, Any]:
        return {
            "device_id": self.device_uuid,
            "status": self.online_status,
            "last_online_at": datetime.now(timezone.utc).isoformat(),
            "system_uptime": self.uptime,
            "cpu_usage": self.cpu,
            "ram_usage": self.ram,
            "disk_usage": self.disk,
            "runtime_version": self.runtime_version,
            "application_version": self.application_version,
            "device_profile": {
                "heartbeat": {
                    "network": self.network,
                    "runtime_version": self.runtime_version,
                    "application_version": self.application_version,
                }
            },
        }


@dataclass
class CloudRuntimeHooks:
    """Runtime callbacks invoked by remote commands."""

    restart_runtime: Callable[[], None] | None = None
    restart_service: Callable[[str], None] | None = None
    refresh_config: Callable[[], None] | None = None
    sync_profile: Callable[[], None] | None = None
    shutdown_host: Callable[[], None] | None = None
    reboot_host: Callable[[], None] | None = None


@dataclass(order=True)
class QueuedCommand:
    """Command retained locally until cloud connectivity returns."""

    sort_index: datetime
    record: RemoteCommandRecord = field(compare=False)
    expires_at: datetime = field(compare=False)


class OfflineCommandQueue:
    """Thread-safe offline command queue with TTL expiry."""

    def __init__(self, *, ttl_seconds: int = COMMAND_TTL_SECONDS) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._items: Deque[QueuedCommand] = deque()
        self._lock = threading.RLock()

    def enqueue(self, record: RemoteCommandRecord) -> None:
        now = datetime.now(timezone.utc)
        created_at = _parse_timestamp(record.created_at) or now
        with self._lock:
            self._items.append(
                QueuedCommand(
                    sort_index=created_at,
                    record=record,
                    expires_at=created_at + self._ttl,
                )
            )

    def drain_valid(self) -> list[RemoteCommandRecord]:
        now = datetime.now(timezone.utc)
        valid: list[RemoteCommandRecord] = []
        with self._lock:
            while self._items:
                item = self._items[0]
                if item.expires_at < now:
                    self._items.popleft()
                    continue
                valid.append(self._items.popleft().record)
        return valid

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _disk_usage_percent() -> float:
    path = "C:\\" if platform.system() == "Windows" else "/"
    return float(psutil.disk_usage(path).percent)


def _network_counters() -> dict[str, int]:
    counters = psutil.net_io_counters()
    if counters is None:
        return {"bytes_sent": 0, "bytes_recv": 0, "packets_sent": 0, "packets_recv": 0}
    return {
        "bytes_sent": int(counters.bytes_sent),
        "bytes_recv": int(counters.bytes_recv),
        "packets_sent": int(counters.packets_sent),
        "packets_recv": int(counters.packets_recv),
    }


def default_reboot_host() -> None:
    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["shutdown", "/r", "/t", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    subprocess.Popen(["/sbin/reboot"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def default_shutdown_host() -> None:
    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["shutdown", "/s", "/t", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    subprocess.Popen(["/sbin/shutdown", "-h", "now"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class DeviceCloudManager:
    """Persistent cloud manager for heartbeat telemetry and remote commands."""

    def __init__(
        self,
        supabase: Client,
        *,
        device_uuid: str,
        event_bus: EventBus | None = None,
        hooks: CloudRuntimeHooks | None = None,
        heartbeat_interval_seconds: int = HEARTBEAT_INTERVAL_SECONDS,
        command_poll_interval_seconds: int = COMMAND_POLL_INTERVAL_SECONDS,
        logger: logging.Logger | None = None,
    ) -> None:
        self._supabase = supabase
        self._device_uuid = device_uuid
        self._event_bus = event_bus or EventBus.get_instance()
        self._hooks = hooks or CloudRuntimeHooks(
            reboot_host=default_reboot_host,
            shutdown_host=default_shutdown_host,
        )
        self._heartbeat_interval = heartbeat_interval_seconds
        self._command_poll_interval = command_poll_interval_seconds
        self._logger = logger or get_logger("cloud.device_manager")
        self._offline_queue = OfflineCommandQueue()
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._connection_status = ConnectionStatus.DISCONNECTED
        self._backoff_seconds = INITIAL_BACKOFF_SECONDS
        self._handlers: dict[str, Callable[[RemoteCommandRecord], None]] = {
            "ping": self._handle_ping,
            "reboot": self._handle_reboot,
            "shutdown": self._handle_shutdown,
            "restart_runtime": self._handle_restart_runtime,
            "restart_service": self._handle_restart_service,
            "refresh_config": self._handle_refresh_config,
            "sync_profile": self._handle_sync_profile,
        }

    @property
    def connection_status(self) -> ConnectionStatus:
        with self._lock:
            return self._connection_status

    @property
    def offline_queue_size(self) -> int:
        return len(self._offline_queue)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_async_loop,
            name="device-cloud-manager",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._cancel_async_tasks)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self._heartbeat_interval + self._command_poll_interval + 5)

    def join(self) -> None:
        if self._thread:
            self._thread.join()

    def collect_metrics(self) -> HeartbeatMetrics:
        return HeartbeatMetrics(
            device_uuid=self._device_uuid,
            online_status=ONLINE_STATUS,
            uptime=int(time.time() - psutil.boot_time()),
            cpu=float(psutil.cpu_percent(interval=0.1)),
            ram=float(psutil.virtual_memory().percent),
            disk=_disk_usage_percent(),
            network=_network_counters(),
            runtime_version=RUNTIME_VERSION,
            application_version=APPLICATION_VERSION,
        )

    def _run_async_loop(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._async_main())
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            self._loop = None

    def _cancel_async_tasks(self) -> None:
        if self._loop is None:
            return
        for task in asyncio.all_tasks(self._loop):
            task.cancel()

    async def _async_main(self) -> None:
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="cloud-heartbeat")
        command_task = asyncio.create_task(self._command_loop(), name="cloud-commands")
        try:
            await asyncio.gather(heartbeat_task, command_task)
        except asyncio.CancelledError:
            pass
        finally:
            heartbeat_task.cancel()
            command_task.cancel()
            await asyncio.gather(heartbeat_task, command_task, return_exceptions=True)

    async def _heartbeat_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._send_heartbeat()
            except Exception:
                self._logger.exception("Heartbeat loop failure")
            await self._sleep_or_stop(self._heartbeat_interval)

    async def _command_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await self._poll_and_execute_commands()
            except Exception:
                self._logger.exception("Command loop failure")
            await self._sleep_or_stop(self._command_poll_interval)

    async def _sleep_or_stop(self, seconds: float) -> None:
        elapsed = 0.0
        while elapsed < seconds and not self._stop_event.is_set():
            await asyncio.sleep(min(0.5, seconds - elapsed))
            elapsed += 0.5

    async def _send_heartbeat(self) -> None:
        metrics = self.collect_metrics()

        def _push() -> None:
            self._supabase.table("devices_enhanced").upsert(
                metrics.to_cloud_record(),
                on_conflict="device_id",
            ).execute()

        await self._with_connection(_push)
        self._event_bus.publish(
            HeartbeatReceived(
                device_uuid=metrics.device_uuid,
                uptime=metrics.uptime,
                cpu=metrics.cpu,
                ram=metrics.ram,
            )
        )
        self._logger.info("Heartbeat received by cloud for %s", metrics.device_uuid)

    async def _poll_and_execute_commands(self) -> None:
        remote_commands = await self._with_connection(self._fetch_pending_commands)
        queued_commands = self._offline_queue.drain_valid()
        for record in [*queued_commands, *remote_commands]:
            await self._execute_command(record)

    def _fetch_pending_commands(self) -> list[RemoteCommandRecord]:
        response = (
            self._supabase.table("device_commands")
            .select("id, device_id, command, status, created_at")
            .eq("device_id", self._device_uuid)
            .eq("status", COMMAND_STATUS_PENDING)
            .order("created_at")
            .execute()
        )
        rows = cast(list[dict[str, Any]], response.data or [])
        return [RemoteCommandRecord(**row) for row in rows]

    async def _execute_command(self, record: RemoteCommandRecord) -> None:
        if not self._is_command_valid(record):
            await asyncio.to_thread(self._mark_failed, record.id, "expired command")
            self._event_bus.publish(
                RemoteCommandFailed(
                    command_id=record.id,
                    command=record.command,
                    error="expired command",
                )
            )
            return

        self._event_bus.publish(
            RemoteCommandReceived(
                command_id=record.id,
                command=record.command,
                device_uuid=record.device_id,
            )
        )

        try:
            await asyncio.to_thread(self._dispatch_command, record)
            await asyncio.to_thread(self._mark_done, record.id)
            self._event_bus.publish(
                RemoteCommandExecuted(
                    command_id=record.id,
                    command=record.command,
                    device_uuid=record.device_id,
                )
            )
        except Exception as exc:
            self._logger.exception("Remote command failed: %s", record.command)
            if self._connection_status is not ConnectionStatus.CONNECTED:
                self._offline_queue.enqueue(record)
            else:
                await asyncio.to_thread(self._mark_failed, record.id, str(exc))
            self._event_bus.publish(
                RemoteCommandFailed(
                    command_id=record.id,
                    command=record.command,
                    error=str(exc),
                )
            )

    def _dispatch_command(self, record: RemoteCommandRecord) -> None:
        normalized = record.command.strip()
        if ":" in normalized:
            command_name, argument = normalized.split(":", 1)
        else:
            command_name, argument = normalized, ""

        command_key = command_name.lower()
        handler = self._handlers.get(command_key)
        if handler is None:
            raise ValueError(f"Unsupported remote command: {record.command}")

        if command_key == "restart_service":
            service_name = argument.strip() or command_name.strip()
            if service_name.lower() == "restart_service" or not argument.strip():
                raise ValueError("restart_service requires a service name")
            handler(
                RemoteCommandRecord(
                    id=record.id,
                    device_id=record.device_id,
                    command=argument.strip(),
                    status=record.status,
                    created_at=record.created_at,
                )
            )
            return

        handler(record)

    def _is_command_valid(self, record: RemoteCommandRecord) -> bool:
        created_at = _parse_timestamp(record.created_at)
        if created_at is None:
            return True
        return created_at + timedelta(seconds=COMMAND_TTL_SECONDS) >= datetime.now(timezone.utc)

    def _mark_done(self, command_id: str) -> None:
        self._supabase.table("device_commands").update(
            {
                "status": COMMAND_STATUS_DONE,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", command_id).execute()

    def _mark_failed(self, command_id: str, error: str) -> None:
        self._supabase.table("device_commands").update(
            {
                "status": COMMAND_STATUS_FAILED,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("id", command_id).execute()
        self._logger.error("Marked command %s failed: %s", command_id, error)

    async def _with_connection(self, operation: Callable[[], Any]) -> Any:
        while not self._stop_event.is_set():
            try:
                result = await asyncio.to_thread(operation)
            except Exception:
                with self._lock:
                    self._connection_status = ConnectionStatus.RECONNECTING
                self._logger.exception("Cloud operation failed; retrying in %.1fs", self._backoff_seconds)
                await self._sleep_or_stop(self._backoff_seconds)
                with self._lock:
                    self._backoff_seconds = min(self._backoff_seconds * 2, MAX_BACKOFF_SECONDS)
                continue

            with self._lock:
                self._connection_status = ConnectionStatus.CONNECTED
                self._backoff_seconds = INITIAL_BACKOFF_SECONDS
            return result

        raise RuntimeError("Device cloud manager stopped")

    def _handle_ping(self, _: RemoteCommandRecord) -> None:
        self._logger.info("PONG")

    def _handle_reboot(self, _: RemoteCommandRecord) -> None:
        if self._hooks.reboot_host is None:
            raise RuntimeError("Reboot hook is not configured")
        self._hooks.reboot_host()

    def _handle_shutdown(self, _: RemoteCommandRecord) -> None:
        if self._hooks.shutdown_host is None:
            raise RuntimeError("Shutdown hook is not configured")
        self._hooks.shutdown_host()

    def _handle_restart_runtime(self, _: RemoteCommandRecord) -> None:
        if self._hooks.restart_runtime is None:
            raise RuntimeError("Restart runtime hook is not configured")
        self._hooks.restart_runtime()

    def _handle_restart_service(self, record: RemoteCommandRecord) -> None:
        if self._hooks.restart_service is None:
            raise RuntimeError("Restart service hook is not configured")
        service_name = record.command.strip()
        if not service_name:
            raise ValueError("restart_service requires a service name")
        self._hooks.restart_service(service_name)

    def _handle_refresh_config(self, _: RemoteCommandRecord) -> None:
        if self._hooks.refresh_config is None:
            raise RuntimeError("Refresh config hook is not configured")
        self._hooks.refresh_config()

    def _handle_sync_profile(self, _: RemoteCommandRecord) -> None:
        if self._hooks.sync_profile is None:
            raise RuntimeError("Sync profile hook is not configured")
        self._hooks.sync_profile()
