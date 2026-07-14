from __future__ import annotations

import socket
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import psutil

from ottomandevice.core.exceptions import HealthCheckError


@dataclass(frozen=True)
class MetricValue:
    """Single health metric reading."""

    name: str
    value: float
    unit: str
    status: str


@dataclass(frozen=True)
class SystemHealthReport:
    """Structured system health report."""

    timestamp: datetime
    status: str
    metrics: tuple[MetricValue, ...] = field(default_factory=tuple)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to a plain dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "metrics": [
                {
                    "name": metric.name,
                    "value": metric.value,
                    "unit": metric.unit,
                    "status": metric.status,
                }
                for metric in self.metrics
            ],
            "details": self.details,
        }


class HealthMonitor:
    """Collects host-level health metrics for the runtime."""

    def __init__(
        self,
        *,
        cpu_warn_threshold: float = 90.0,
        memory_warn_threshold: float = 90.0,
        disk_warn_threshold: float = 90.0,
    ) -> None:
        self._cpu_warn_threshold = cpu_warn_threshold
        self._memory_warn_threshold = memory_warn_threshold
        self._disk_warn_threshold = disk_warn_threshold
        self._last_network: Any | None = None
        self._last_network_at: float | None = None

    def collect(self) -> SystemHealthReport:
        """Collect current CPU, memory, disk, and network health metrics."""
        metrics: list[MetricValue] = []
        details: dict[str, Any] = {}

        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_status = "warn" if cpu_percent >= self._cpu_warn_threshold else "ok"
        metrics.append(MetricValue("cpu_percent", cpu_percent, "%", cpu_status))
        details["cpu_count"] = psutil.cpu_count(logical=True)

        memory = psutil.virtual_memory()
        memory_status = "warn" if memory.percent >= self._memory_warn_threshold else "ok"
        metrics.append(MetricValue("memory_percent", memory.percent, "%", memory_status))
        details["memory_available_bytes"] = memory.available
        details["memory_total_bytes"] = memory.total

        disk_path = self._resolve_disk_path()
        disk = psutil.disk_usage(disk_path)
        disk_percent = (disk.used / disk.total) * 100 if disk.total else 0.0
        disk_status = "warn" if disk_percent >= self._disk_warn_threshold else "ok"
        metrics.append(MetricValue("disk_percent", disk_percent, "%", disk_status))
        details["disk_path"] = disk_path
        details["disk_free_bytes"] = disk.free
        details["disk_total_bytes"] = disk.total

        network_metrics, network_details = self._collect_network()
        metrics.extend(network_metrics)
        details.update(network_details)

        overall_status = "warn" if any(metric.status == "warn" for metric in metrics) else "ok"
        return SystemHealthReport(
            timestamp=datetime.now(timezone.utc),
            status=overall_status,
            metrics=tuple(metrics),
            details=details,
        )

    def check(self) -> SystemHealthReport:
        """Collect health metrics and raise when collection fails."""
        try:
            return self.collect()
        except Exception as exc:
            raise HealthCheckError(f"Health collection failed: {exc}") from exc

    def _resolve_disk_path(self) -> str:
        if hasattr(psutil, "WINDOWS") and psutil.WINDOWS:
            return "C:\\"
        return "/"

    def _collect_network(self) -> tuple[list[MetricValue], dict[str, Any]]:
        counters = psutil.net_io_counters()
        now = time.monotonic()
        metrics: list[MetricValue] = []
        details: dict[str, Any] = {
            "bytes_sent": counters.bytes_sent,
            "bytes_recv": counters.bytes_recv,
            "packets_sent": counters.packets_sent,
            "packets_recv": counters.packets_recv,
        }

        if self._last_network is not None and self._last_network_at is not None:
            elapsed = max(now - self._last_network_at, 0.001)
            send_rate = (counters.bytes_sent - self._last_network.bytes_sent) / elapsed
            recv_rate = (counters.bytes_recv - self._last_network.bytes_recv) / elapsed
            metrics.append(MetricValue("network_send_bps", send_rate, "B/s", "ok"))
            metrics.append(MetricValue("network_recv_bps", recv_rate, "B/s", "ok"))

        self._last_network = counters
        self._last_network_at = now

        try:
            details["hostname"] = socket.gethostname()
        except OSError:
            details["hostname"] = "unknown"

        return metrics, details
