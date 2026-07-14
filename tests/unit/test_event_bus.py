from __future__ import annotations

import asyncio
import threading
import time

import pytest

from ottomandevice.core.event_bus import (
    Event,
    EventBus,
    HealthUpdated,
    RuntimeStarted,
    ServiceFailed,
    ServiceStarted,
    ServiceStopped,
)
from ottomandevice.core.service import BaseService, ServiceState


class _RecordingService(BaseService):
    def __init__(self, *, fail_start: bool = False) -> None:
        super().__init__("stub", required=False, restartable=True)
        self.fail_start = fail_start
        self.started = False
        self.stopped = False

    def on_start(self) -> None:
        if self.fail_start:
            raise RuntimeError("start failed")
        self.started = True

    def on_stop(self) -> None:
        self.stopped = True


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=10)
    yield event_bus
    event_bus.shutdown()


def test_publish_records_history(bus: EventBus) -> None:
    event = RuntimeStarted()
    bus.publish(event)

    assert len(bus.history) == 1
    assert bus.history[0].event_type == "RuntimeStarted"


def test_subscribe_and_unsubscribe(bus: EventBus) -> None:
    received: list[str] = []

    subscription_id = bus.subscribe("RuntimeStarted", lambda event: received.append(event.event_type))

    bus.publish(RuntimeStarted())
    assert received == ["RuntimeStarted"]

    assert bus.unsubscribe(subscription_id) is True
    bus.publish(RuntimeStarted())
    assert received == ["RuntimeStarted"]


def test_subscribe_decorator(bus: EventBus) -> None:
    received: list[str] = []

    @bus.subscribe("ServiceStarted")
    def handler(event: Event) -> None:
        received.append(event.event_type)

    bus.publish(ServiceStarted(service_name="heartbeat"))
    assert received == ["ServiceStarted"]


def test_wildcard_subscription(bus: EventBus) -> None:
    received: list[str] = []

    bus.subscribe("Service*", lambda event: received.append(event.event_type))
    bus.subscribe("*", lambda event: received.append(f"all:{event.event_type}"))

    bus.publish(ServiceStarted(service_name="telemetry"))
    bus.publish(RuntimeStarted())

    assert "ServiceStarted" in received
    assert "all:ServiceStarted" in received
    assert "all:RuntimeStarted" in received


def test_priority_dispatch_order(bus: EventBus) -> None:
    order: list[int] = []

    bus.subscribe("HealthUpdated", lambda _event: order.append(1), priority=1)
    bus.subscribe("HealthUpdated", lambda _event: order.append(10), priority=10)
    bus.subscribe("HealthUpdated", lambda _event: order.append(5), priority=5)

    bus.publish(HealthUpdated(status="ok"))
    assert order == [10, 5, 1]


def test_history_is_capped() -> None:
    bus = EventBus(max_history=3)
    try:
        for index in range(5):
            bus.publish(RuntimeStarted(payload={"index": index}))
        assert len(bus.history) == 3
        assert bus.history[0].payload["index"] == 2
        assert bus.history[-1].payload["index"] == 4
    finally:
        bus.shutdown()


def test_async_handler_dispatch(bus: EventBus) -> None:
    seen = threading.Event()

    async def handler(_event: Event) -> None:
        seen.set()

    bus.subscribe("RuntimeStarted", handler)
    bus.publish(RuntimeStarted())

    assert seen.wait(timeout=2) is True


def test_builtin_event_payloads() -> None:
    started = ServiceStarted(service_name="heartbeat")
    failed = ServiceFailed(service_name="heartbeat", error="boom", context="start")
    stopped = ServiceStopped(service_name="heartbeat")

    assert started.to_dict()["payload"]["service_name"] == "heartbeat"
    assert failed.to_dict()["payload"]["error"] == "boom"
    assert stopped.to_dict()["payload"]["service_name"] == "heartbeat"


def test_base_service_publishes_lifecycle_events() -> None:
    bus = EventBus()
    service = _RecordingService()
    service._event_bus = bus

    try:
        service.start()
        service.stop()

        types = [event.event_type for event in bus.history]
        assert types == ["ServiceStarted", "ServiceStopped"]
    finally:
        bus.shutdown()


def test_base_service_publishes_failure_event() -> None:
    bus = EventBus()
    service = _RecordingService(fail_start=True)
    service._event_bus = bus

    try:
        with pytest.raises(Exception):
            service.start()
        assert bus.history[-1].event_type == "ServiceFailed"
        assert service.state == ServiceState.FAILED
    finally:
        bus.shutdown()


def test_supervisor_publishes_max_restart_failure() -> None:
    from ottomandevice.core.supervisor import ServiceSupervisor

    bus = EventBus()
    supervisor = ServiceSupervisor(
        restart_delay_seconds=0.01,
        max_restarts=0,
        event_bus=bus,
    )
    service = _RecordingService(fail_start=True)
    service._event_bus = bus
    supervisor.register(service)

    try:
        supervisor.start_all()
        failed_events = [event for event in bus.history if event.event_type == "ServiceFailed"]
        assert failed_events
        assert any(event.payload.get("context") == "start" for event in failed_events)
    finally:
        bus.shutdown()
