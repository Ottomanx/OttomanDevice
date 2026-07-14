from __future__ import annotations

import time
from pathlib import Path

import pytest

from ottomandevice.core.config import ConfigManager
from ottomandevice.core.exceptions import ExceptionManager
from ottomandevice.core.health import HealthMonitor
from ottomandevice.core.logger import configure_logging, get_logger
from ottomandevice.core.performance import PerformanceMonitor
from ottomandevice.core.service import BaseService, LegacyServiceAdapter, ServiceState
from ottomandevice.core.supervisor import ServiceSupervisor


class _StubService(BaseService):
    def __init__(self, *, fail_start: bool = False, fail_stop: bool = False) -> None:
        super().__init__("stub", required=False, restartable=True)
        self.fail_start = fail_start
        self.fail_stop = fail_stop
        self.started = False
        self.stopped = False

    def on_start(self) -> None:
        if self.fail_start:
            raise RuntimeError("start failed")
        self.started = True

    def on_stop(self) -> None:
        if self.fail_stop:
            raise RuntimeError("stop failed")
        self.stopped = True


class _LegacyService:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


def test_configure_logging_creates_daily_log_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTTOMAN_LOG_DIR", str(tmp_path))
    configure_logging(force=True)

    logger = get_logger("test")
    logger.info("hello")

    day_dirs = [path for path in tmp_path.iterdir() if path.is_dir()]
    assert len(day_dirs) == 1
    log_file = day_dirs[0] / "ottomandevice.log"
    assert log_file.exists()
    assert "hello" in log_file.read_text(encoding="utf-8")


def test_config_manager_loads_runtime_defaults() -> None:
    manager = ConfigManager.get_instance()
    settings = manager.load()

    assert settings.heartbeat.interval == 30
    assert manager.runtime.log_level == "INFO"
    assert manager.runtime.supervisor_max_restarts == 10


def test_exception_manager_records_failures() -> None:
    manager = ExceptionManager.get_instance()
    manager.clear()

    record = manager.report(RuntimeError("boom"), service="telemetry", context="start")

    assert record.service == "telemetry"
    assert "start" in record.message
    assert manager.latest("telemetry") is record


def test_performance_monitor_tracks_context_and_decorator() -> None:
    monitor = PerformanceMonitor.get_instance()
    monitor.clear()

    with monitor.measure("block"):
        time.sleep(0.01)

    @monitor.timed("fn")
    def sample() -> str:
        time.sleep(0.01)
        return "ok"

    assert sample() == "ok"

    stats = monitor.stats("block")
    assert "block" in stats
    assert stats["block"].count == 1
    assert stats["block"].average_ms > 0


def test_health_monitor_returns_structured_report() -> None:
    monitor = HealthMonitor()
    report = monitor.collect()

    assert report.status in {"ok", "warn"}
    metric_names = {metric.name for metric in report.metrics}
    assert "cpu_percent" in metric_names
    assert "memory_percent" in metric_names
    assert "disk_percent" in metric_names
    payload = report.to_dict()
    assert payload["status"] == report.status
    assert isinstance(payload["metrics"], list)


def test_base_service_lifecycle() -> None:
    service = _StubService()
    assert service.state == ServiceState.STOPPED

    service.start()
    assert service.state == ServiceState.RUNNING
    assert service.started is True

    service.stop()
    assert service.state == ServiceState.STOPPED
    assert service.stopped is True


def test_legacy_service_adapter_wraps_start_stop() -> None:
    legacy = _LegacyService()
    adapter = LegacyServiceAdapter("legacy", legacy)

    adapter.start()
    adapter.stop()

    assert legacy.started is True
    assert legacy.stopped is True


def test_service_supervisor_starts_and_stops_services() -> None:
    supervisor = ServiceSupervisor()
    service = _StubService()
    supervisor.register(service)

    supervisor.start_all()
    assert service.state == ServiceState.RUNNING

    supervisor.stop_all()
    assert service.state == ServiceState.STOPPED


def test_service_supervisor_restarts_failed_service() -> None:
    supervisor = ServiceSupervisor(restart_delay_seconds=0.05, max_restarts=2)
    service = _StubService(fail_start=True)
    supervisor.register(service)

    supervisor.start_all()
    assert service.state == ServiceState.FAILED

    service.fail_start = False
    supervisor.restart_service("stub")
    assert service.state == ServiceState.RUNNING


def test_service_registry_delegates_to_supervisor() -> None:
    from ottomandevice.core.service_registry import ServiceRegistry

    registry = ServiceRegistry()
    legacy = _LegacyService()
    registry.register(legacy)

    registry.start_all()
    assert legacy.started is True

    registry.stop_all()
    assert legacy.stopped is True