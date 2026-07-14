from __future__ import annotations

from ottomandevice.logging import get_logger

monitor_logger = get_logger("remote_desktop.monitor")


def log_monitor_switch(
    *,
    from_monitor: str | None,
    to_monitor: str,
    duration_ms: float,
    success: bool,
) -> None:
    monitor_logger.info(
        "Monitor switch from_monitor=%s to_monitor=%s duration_ms=%.2f success=%s",
        from_monitor,
        to_monitor,
        duration_ms,
        success,
    )
