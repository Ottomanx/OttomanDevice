from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ottomandevice.cloud.device_manager import (
    CloudRuntimeHooks,
    DeviceCloudManager,
    OfflineCommandQueue,
    RemoteCommandRecord,
)
from ottomandevice.core.event_bus import EventBus


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=100)
    yield event_bus
    event_bus.shutdown()


def _build_manager(
    bus: EventBus,
    *,
    hooks: CloudRuntimeHooks | None = None,
) -> tuple[DeviceCloudManager, MagicMock]:
    supabase = MagicMock()
    table = supabase.table.return_value
    table.select.return_value.eq.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
        data=[]
    )
    table.upsert.return_value.execute.return_value = MagicMock(data=[])
    table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    manager = DeviceCloudManager(
        supabase,
        device_uuid="device-123",
        event_bus=bus,
        hooks=hooks,
        heartbeat_interval_seconds=1,
        command_poll_interval_seconds=1,
    )
    return manager, supabase


def test_collect_metrics_contains_required_fields(bus: EventBus) -> None:
    manager, _ = _build_manager(bus)
    metrics = manager.collect_metrics()

    assert metrics.device_uuid == "device-123"
    assert metrics.online_status == "ONLINE"
    assert metrics.uptime >= 0
    assert 0 <= metrics.cpu <= 100
    assert 0 <= metrics.ram <= 100
    assert 0 <= metrics.disk <= 100
    assert "bytes_sent" in metrics.network
    assert metrics.runtime_version
    assert metrics.application_version


@pytest.mark.asyncio
async def test_send_heartbeat_publishes_event(bus: EventBus) -> None:
    manager, _ = _build_manager(bus)
    received: list[str] = []
    bus.subscribe("HeartbeatReceived", lambda event: received.append(event.event_type))

    await manager._send_heartbeat()

    assert received == ["HeartbeatReceived"]


def test_execute_ping_command(bus: EventBus) -> None:
    manager, supabase = _build_manager(bus)
    record = RemoteCommandRecord(
        id="cmd-1",
        device_id="device-123",
        command="ping",
        status="PENDING",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    received: list[str] = []
    bus.subscribe("RemoteCommand*", lambda event: received.append(event.event_type))

    asyncio.run(manager._execute_command(record))

    assert "RemoteCommandReceived" in received
    assert "RemoteCommandExecuted" in received
    supabase.table.return_value.update.assert_called()


def test_unsupported_command_publishes_failure(bus: EventBus) -> None:
    manager, _ = _build_manager(bus)
    record = RemoteCommandRecord(
        id="cmd-2",
        device_id="device-123",
        command="unknown_command",
        status="PENDING",
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    received: list[str] = []
    bus.subscribe("RemoteCommandFailed", lambda event: received.append(event.event_type))

    asyncio.run(manager._execute_command(record))

    assert received == ["RemoteCommandFailed"]


def test_restart_service_invokes_hook(bus: EventBus) -> None:
    restarted: list[str] = []

    hooks = CloudRuntimeHooks(restart_service=restarted.append)
    manager, _ = _build_manager(bus, hooks=hooks)
    record = RemoteCommandRecord(
        id="cmd-3",
        device_id="device-123",
        command="restart_service:telemetry",
        status="PENDING",
        created_at=datetime.now(timezone.utc).isoformat(),
    )

    manager._dispatch_command(record)

    assert restarted == ["telemetry"]


def test_restart_service_requires_service_name(bus: EventBus) -> None:
    manager, _ = _build_manager(bus)
    record = RemoteCommandRecord(
        id="cmd-4",
        device_id="device-123",
        command="restart_service",
        status="PENDING",
    )

    with pytest.raises(ValueError):
        manager._dispatch_command(record)


def test_offline_queue_drains_valid_commands() -> None:
    queue = OfflineCommandQueue(ttl_seconds=3600)
    now = datetime.now(timezone.utc)
    record = RemoteCommandRecord(
        id="queued-1",
        device_id="device-123",
        command="ping",
        status="PENDING",
        created_at=now.isoformat(),
    )
    queue.enqueue(record)

    drained = queue.drain_valid()

    assert len(drained) == 1
    assert drained[0].id == "queued-1"
    assert len(queue) == 0


def test_offline_queue_drops_expired_commands() -> None:
    queue = OfflineCommandQueue(ttl_seconds=60)
    expired = RemoteCommandRecord(
        id="queued-2",
        device_id="device-123",
        command="ping",
        status="PENDING",
        created_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
    )
    queue.enqueue(expired)

    assert queue.drain_valid() == []


@pytest.mark.asyncio
async def test_connection_backoff_resets_after_success(bus: EventBus) -> None:
    manager, _ = _build_manager(bus)
    calls = {"count": 0}

    def flaky() -> str:
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary outage")
        return "ok"

    result = await manager._with_connection(flaky)

    assert result == "ok"
    assert calls["count"] == 2
    assert manager._backoff_seconds == 1.0
    assert manager.connection_status.value == "connected"


def test_sync_profile_hook_executes(bus: EventBus) -> None:
    synced: list[str] = []
    hooks = CloudRuntimeHooks(sync_profile=lambda: synced.append("called"))
    manager, _ = _build_manager(bus, hooks=hooks)
    record = RemoteCommandRecord(
        id="cmd-5",
        device_id="device-123",
        command="sync_profile",
        status="PENDING",
    )

    manager._dispatch_command(record)

    assert synced == ["called"]
