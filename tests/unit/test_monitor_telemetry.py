from __future__ import annotations

from ottomandevice.remote_desktop.monitor.telemetry import log_monitor_switch


def test_log_monitor_switch(caplog) -> None:
    with caplog.at_level("INFO"):
        log_monitor_switch(
            from_monitor="display-1",
            to_monitor="display-2",
            duration_ms=42.5,
            success=True,
        )
    assert "Monitor switch" in caplog.text
    assert "display-1" in caplog.text
    assert "display-2" in caplog.text
    assert "success=True" in caplog.text
