from __future__ import annotations

import pytest

from ottomandevice.remote_desktop.input_injector import InputInjector
from ottomandevice.remote_desktop.monitor.enumerator import DisplayEnumerator
from ottomandevice.remote_desktop.monitor.manager import MonitorManager, MonitorError
from ottomandevice.remote_desktop.monitor.models import MonitorChangeType, MonitorInfo


class StaticDisplayEnumerator(DisplayEnumerator):
    def __init__(self, monitors: list[MonitorInfo]) -> None:
        self._monitors = monitors

    def enumerate(self) -> list[MonitorInfo]:
        return list(self._monitors)


class MockCaptureEngine:
    def __init__(self) -> None:
        self.active: MonitorInfo | None = None

    def set_active_monitor(self, monitor: MonitorInfo | None) -> None:
        self.active = monitor


class MockStreamRunner:
    def __init__(self) -> None:
        self.running = True
        self.immediate_requests = 0

    @property
    def is_running(self) -> bool:
        return self.running

    def request_immediate_frame(self) -> None:
        self.immediate_requests += 1


def _two_monitors() -> list[MonitorInfo]:
    return [
        MonitorInfo(
            id="display-1",
            number=1,
            width=1920,
            height=1080,
            x=0,
            y=0,
            is_primary=True,
        ),
        MonitorInfo(
            id="display-2",
            number=2,
            width=1280,
            height=720,
            x=1920,
            y=0,
            is_primary=False,
        ),
    ]


@pytest.mark.asyncio
async def test_initialize_selects_primary_monitor() -> None:
    capture = MockCaptureEngine()
    injector = InputInjector()
    manager = MonitorManager(
        enumerator=StaticDisplayEnumerator(_two_monitors()),
        capture_engine=capture,
        input_injector=injector,
    )
    await manager.initialize()
    assert manager.selected_id == "display-1"
    assert capture.active is not None
    assert capture.active.width == 1920


@pytest.mark.asyncio
async def test_select_monitor_rejects_unknown_id() -> None:
    capture = MockCaptureEngine()
    manager = MonitorManager(
        enumerator=StaticDisplayEnumerator(_two_monitors()),
        capture_engine=capture,
        input_injector=InputInjector(),
    )
    runner = MockStreamRunner()
    manager.bind_stream_runner(runner)
    await manager.initialize()

    messages: list[dict[str, object]] = []

    async def send_message(_msg_type: str, payload: dict[str, object] | None = None) -> None:
        messages.append(payload or {})

    await manager.select_monitor("missing", send_message)
    assert messages[-1]["accepted"] is False


@pytest.mark.asyncio
async def test_refresh_detects_removed_monitor() -> None:
    monitors = _two_monitors()
    enumerator = StaticDisplayEnumerator(monitors)
    manager = MonitorManager(
        enumerator=enumerator,
        capture_engine=MockCaptureEngine(),
        input_injector=InputInjector(),
    )
    await manager.initialize()
    monitors.pop()
    change = manager.refresh()
    assert change == MonitorChangeType.REMOVED


@pytest.mark.asyncio
async def test_select_requires_active_stream() -> None:
    manager = MonitorManager(
        enumerator=StaticDisplayEnumerator(_two_monitors()),
        capture_engine=MockCaptureEngine(),
        input_injector=InputInjector(),
    )
    await manager.initialize()
    with pytest.raises(MonitorError) as exc:
        await manager.select_monitor("display-2", send_message=async_noop)
    assert exc.value.code == "STREAM_NOT_ACTIVE"


async def async_noop(_msg_type: str, _payload: dict[str, object] | None = None) -> None:
    return
