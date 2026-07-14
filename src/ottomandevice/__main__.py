import os

from dotenv import load_dotenv

from ottomandevice.command import CommandService
from ottomandevice.core import ServiceRegistry
from ottomandevice.desktop_stream import DesktopStreamService
from ottomandevice.heartbeat import HeartbeatService
from ottomandevice.logging import get_logger
from ottomandevice.ota import OtaService
from ottomandevice.remote_desktop import RemoteDesktopService
from ottomandevice.runtime import PROJECT_ROOT
from ottomandevice.startup import (
    HealthReport,
    check_supabase_connection,
    log_health_report,
    print_startup_banner,
    run_startup_health_checks,
    start_service_safely,
    validate_environment,
)
from ottomandevice.telemetry import TelemetryService

logger = get_logger("__main__")


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    env_result = validate_environment()
    for message in env_result.errors:
        logger.error(message)
    for message in env_result.warnings:
        logger.warning(message)
    if env_result.fatal:
        raise SystemExit(1)

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_ANON_KEY", "").strip()
    jwt_secret = os.getenv("REMOTE_DESKTOP_JWT_SECRET", "").strip()
    ota_secret = os.getenv("OTA_SIGNING_SECRET", "").strip()

    health = HealthReport()

    supabase, supabase_status, supabase_message = check_supabase_connection(url, key)
    health.set("supabase", supabase_status, supabase_message)
    if supabase is None or supabase_status == "FAIL":
        raise SystemExit(1)

    health.merge(run_startup_health_checks(
        supabase=supabase,
        jwt_secret=jwt_secret,
        ota_secret=ota_secret,
    ))
    log_health_report(health)

    if health.get("device_registration") == "FAIL":
        logger.error(health.messages.get("device_registration", "Device registration failed"))
        raise SystemExit(1)

    registry = ServiceRegistry()

    heartbeat = HeartbeatService(supabase)
    command_service = CommandService(supabase, heartbeat_service=heartbeat)
    telemetry_service = TelemetryService(supabase)

    registry.register(heartbeat)
    registry.register(command_service)
    registry.register(telemetry_service)

    desktop_stream: DesktopStreamService | None = None
    if health.get("bucket_desktop_preview") == "PASS":
        desktop_stream = DesktopStreamService(supabase)
        registry.register(desktop_stream)
    else:
        health.set("desktop_stream", "WARN", "Desktop stream disabled (bucket missing)")
        logger.warning("Desktop stream disabled (bucket missing)")

    remote_desktop_service = RemoteDesktopService(
        desktop_stream_service=desktop_stream,
        jwt_secret=jwt_secret or None,
    )
    registry.register(remote_desktop_service)

    ota_service: OtaService | None = None
    if ota_secret:
        ota_service = OtaService(supabase, signing_secret=ota_secret)
        registry.register(ota_service)
    else:
        health.set("ota", "DISABLED", "OTA disabled (signing secret missing)")

    heartbeat_status, heartbeat_message = start_service_safely(heartbeat, "Heartbeat", required=True)
    health.set("heartbeat", heartbeat_status, heartbeat_message)

    command_status, command_message = start_service_safely(command_service, "Command", required=True)
    if command_status != "PASS":
        logger.error(command_message)
        raise SystemExit(1)

    telemetry_status, telemetry_message = start_service_safely(telemetry_service, "Telemetry", required=True)
    health.set("telemetry", telemetry_status, telemetry_message)

    if desktop_stream is not None:
        desktop_status, desktop_message = start_service_safely(
            desktop_stream,
            "Desktop Stream",
            required=False,
        )
        health.set("desktop_stream", desktop_status, desktop_message)
        if desktop_status != "PASS":
            logger.warning(desktop_message)

    remote_status, remote_message = start_service_safely(
        remote_desktop_service,
        "Remote Desktop",
        required=False,
    )
    health.set("remote_desktop", remote_status, remote_message)
    if remote_status != "PASS":
        logger.warning(remote_message)

    if ota_service is not None:
        ota_status, ota_message = start_service_safely(ota_service, "OTA", required=False)
        health.set("ota", ota_status, ota_message)
        if ota_status != "PASS":
            logger.warning(ota_message)

    print_startup_banner(health)

    try:
        heartbeat.join()
    except KeyboardInterrupt:
        logger.info("Shutdown requested")
        registry.stop_all()
        logger.info("All services stopped")


if __name__ == "__main__":
    main()
