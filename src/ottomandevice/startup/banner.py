from __future__ import annotations

from ottomandevice.logging import get_logger
from ottomandevice.startup.health import HealthReport, HealthStatus

AGENT_VERSION = "0.2.0"
logger = get_logger("startup")


def log_health_report(report: HealthReport) -> None:
    for name, status in report.checks.items():
        detail = report.messages.get(name, "")
        if detail:
            logger.info("%s: %s - %s", name, status, detail)
        else:
            logger.info("%s: %s", name, status)


def _format_status(status: HealthStatus) -> str:
    return status


def print_startup_banner(report: HealthReport) -> None:
    desktop_status = report.get("desktop_stream")
    remote_status = report.get("remote_desktop")
    ota_status = report.get("ota")

    lines = [
        "",
        f"OttomanDevice v{AGENT_VERSION}",
        "",
        f"Supabase ........ {_format_status(report.get('supabase'))}",
        f"Heartbeat ....... {_format_status(report.get('heartbeat'))}",
        f"Telemetry ....... {_format_status(report.get('telemetry'))}",
        f"Desktop Stream .. {_format_status(desktop_status)}",
        f"Remote Desktop .. {_format_status(remote_status)}",
        f"OTA ............. {_format_status(ota_status)}",
        f"Camera .......... {_format_status(report.get('camera'))}",
        "",
        "System Ready",
        "",
    ]

    banner = "\n".join(lines)
    logger.info("Startup summary:%s", banner)
