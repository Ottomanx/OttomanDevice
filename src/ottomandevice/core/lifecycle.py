from __future__ import annotations

import os

from dotenv import load_dotenv
from supabase import Client

from ottomandevice.core.config import ConfigManager
from ottomandevice.core.event_bus import (
    CloudConnected,
    CloudDisconnected,
    EventBus,
    HealthUpdated,
    RuntimeStarted,
    RuntimeStopping,
)
from ottomandevice.core.exceptions import ExceptionManager
from ottomandevice.core.health import HealthMonitor
from ottomandevice.core.logger import configure_logging, get_logger
from ottomandevice.core.performance import PerformanceMonitor
from ottomandevice.core.plugin_manager import PluginManager
from ottomandevice.device.certificate import DeviceCertificate
from ottomandevice.device.identity import DeviceIdentity
from ottomandevice.device.profile import DeviceProfile
from ottomandevice.device.registry import DeviceRegistry
from ottomandevice.core.service import LegacyServiceAdapter
from ottomandevice.core.supervisor import ServiceSupervisor
from ottomandevice.desktop_stream import DesktopStreamService
from ottomandevice.ota import OtaService
from ottomandevice.paths import PROJECT_ROOT
from ottomandevice.remote_desktop import RemoteDesktopService
from ottomandevice.startup import (
    HealthReport,
    check_supabase_connection,
    log_health_report,
    print_startup_banner,
    run_startup_health_checks,
    validate_environment,
)


class Runtime:
    """Production runtime orchestrator for OttomanDevice services."""

    def __init__(self) -> None:
        self._logger = get_logger("runtime")
        self._config = ConfigManager.get_instance()
        self._exceptions = ExceptionManager.get_instance()
        self._performance = PerformanceMonitor.get_instance()
        self._health_monitor = HealthMonitor()
        self._supervisor = ServiceSupervisor()
        self._startup_report = HealthReport()
        self._supabase: Client | None = None
        self._cloud_manager: DeviceCloudManager | None = None
        self._event_bus = EventBus.get_instance()
        self._plugin_manager: PluginManager | None = None
        self._device_identity: DeviceIdentity | None = None
        self._device_registry: DeviceRegistry | None = None

    @property
    def supervisor(self) -> ServiceSupervisor:
        """Return the runtime service supervisor."""
        return self._supervisor

    @property
    def startup_report(self) -> HealthReport:
        """Return the startup health report."""
        return self._startup_report

    def run(self) -> None:
        """Boot the runtime, supervise services, and block until shutdown."""
        load_dotenv(PROJECT_ROOT / ".env")
        self._config.load()
        runtime_config = self._config.runtime
        os.environ.setdefault("OTTOMAN_LOG_LEVEL", runtime_config.log_level)
        os.environ.setdefault("OTTOMAN_LOG_DIR", runtime_config.log_dir)
        configure_logging(force=True)

        self._supervisor = ServiceSupervisor(
            restart_delay_seconds=runtime_config.supervisor_restart_delay_seconds,
            max_restarts=runtime_config.supervisor_max_restarts,
            event_bus=self._event_bus,
        )

        with self._performance.measure("runtime.boot"):
            self._validate_environment()
            self._connect_supabase()
            self._initialize_device_identity()
            self._run_startup_checks()
            self._register_services()
            self._load_plugins()
            self._start_services()
            self._log_system_health()
            print_startup_banner(self._startup_report)

        self._event_bus.publish(RuntimeStarted())

        self._supervisor.supervise(
            poll_interval_seconds=runtime_config.health_check_interval_seconds,
        )

        try:
            self._block_until_shutdown()
        except KeyboardInterrupt:
            self._logger.info("Shutdown requested")
        finally:
            self._shutdown()

    def _validate_environment(self) -> None:
        env_result = validate_environment()
        for message in env_result.errors:
            self._logger.error(message)
        for message in env_result.warnings:
            self._logger.warning(message)
        if env_result.fatal:
            raise SystemExit(1)

    def _connect_supabase(self) -> None:
        url = os.getenv("SUPABASE_URL", "").strip()
        key = os.getenv("SUPABASE_ANON_KEY", "").strip()
        supabase, status, message = check_supabase_connection(url, key)
        self._startup_report.set("supabase", status, message)
        if supabase is None or status == "FAIL":
            raise SystemExit(1)
        self._supabase = supabase
        self._event_bus.publish(CloudConnected())



    def _initialize_device_identity(self) -> None:
        """Load local identity and ensure device certificate material exists."""
        self._device_identity = DeviceIdentity.load()
        certificate = DeviceCertificate.ensure(self._device_identity.device_uuid)
        if self._device_identity.certificate_fingerprint != certificate.fingerprint:
            self._device_identity = self._device_identity.with_certificate_fingerprint(
                certificate.fingerprint
            )
            self._device_identity.persist()
        assert self._supabase is not None
        self._device_registry = DeviceRegistry(
            supabase=self._supabase,
            identity=self._device_identity,
            certificate=certificate,
            event_bus=self._event_bus,
        )
        self._logger.info("Device identity loaded: %s", self._device_identity.device_uuid)

    def _run_startup_checks(self) -> None:
        assert self._supabase is not None
        jwt_secret = os.getenv("REMOTE_DESKTOP_JWT_SECRET", "").strip()
        ota_secret = os.getenv("OTA_SIGNING_SECRET", "").strip()
        self._startup_report.merge(
            run_startup_health_checks(
                supabase=self._supabase,
                jwt_secret=jwt_secret,
                ota_secret=ota_secret,
            )
        )
        log_health_report(self._startup_report)

        if self._startup_report.get("device_registration") == "FAIL":
            message = self._startup_report.messages.get(
                "device_registration",
                "Device registration failed",
            )
            self._logger.error(message)
            raise SystemExit(1)

    def _register_services(self) -> None:
        assert self._supabase is not None
        jwt_secret = os.getenv("REMOTE_DESKTOP_JWT_SECRET", "").strip()
        ota_secret = os.getenv("OTA_SIGNING_SECRET", "").strip()

        from ottomandevice.cloud.device_manager import CloudRuntimeHooks, DeviceCloudManager

        assert self._device_identity is not None
        hooks = CloudRuntimeHooks(
            restart_runtime=self._request_runtime_restart,
            restart_service=self._supervisor.restart_service,
            refresh_config=self._config.reload,
            sync_profile=self._sync_device_profile,
        )
        self._cloud_manager = DeviceCloudManager(
            self._supabase,
            device_uuid=self._device_identity.device_uuid,
            event_bus=self._event_bus,
            hooks=hooks,
        )
        self._supervisor.register(
            LegacyServiceAdapter("cloud", self._cloud_manager, required=True, restartable=True)
        )

        desktop_stream: DesktopStreamService | None = None
        if self._startup_report.get("bucket_desktop_preview") == "PASS":
            desktop_stream = DesktopStreamService(self._supabase)
            self._supervisor.register(
                LegacyServiceAdapter(
                    "desktop_stream",
                    desktop_stream,
                    required=False,
                    restartable=True,
                )
            )
        else:
            self._startup_report.set(
                "desktop_stream",
                "WARN",
                "Desktop stream disabled (bucket missing)",
            )
            self._logger.warning("Desktop stream disabled (bucket missing)")

        remote_desktop_service = RemoteDesktopService(
            desktop_stream_service=desktop_stream,
            jwt_secret=jwt_secret or None,
        )
        self._supervisor.register(
            LegacyServiceAdapter(
                "remote_desktop",
                remote_desktop_service,
                required=False,
                restartable=True,
            )
        )

        if ota_secret:
            ota_service = OtaService(self._supabase, signing_secret=ota_secret)
            self._supervisor.register(
                LegacyServiceAdapter("ota", ota_service, required=False, restartable=True)
            )
        else:
            self._startup_report.set("ota", "DISABLED", "OTA disabled (signing secret missing)")



    def _load_plugins(self) -> None:
        """Discover and start runtime plugins in dependency order."""
        self._plugin_manager = PluginManager.get_instance(event_bus=self._event_bus)
        self._plugin_manager.discover()
        self._plugin_manager.load_all()
        self._logger.info("Loaded %s plugin(s)", len(self._plugin_manager.plugins))
        self._sync_device_profile()



    def _sync_device_profile(self) -> None:
        """Publish the runtime device profile after plugins are loaded."""
        if self._device_identity is None or self._device_registry is None:
            return
        profile = DeviceProfile.collect(
            self._device_identity,
            plugin_manager=self._plugin_manager,
        )
        self._device_registry.update_profile(profile)
        self._logger.info(
            "Device profile synchronized (%s plugins)",
            len(profile.plugins),
        )

    def _start_services(self) -> None:
        for service in self._supervisor.services:
            try:
                service.start()
                self._startup_report.set(service.name, "PASS", f"{service.name} started")
            except Exception as exc:
                self._exceptions.report(exc, service=service.name, context="startup")
                if service.required:
                    self._logger.error("Required service %s failed to start", service.name)
                    raise SystemExit(1) from exc
                self._startup_report.set(
                    service.name,
                    "WARN",
                    f"{service.name} disabled: {exc}",
                )
                self._logger.warning("Optional service %s failed to start: %s", service.name, exc)

    def _log_system_health(self) -> None:
        report = self._health_monitor.collect()
        self._logger.info("System health status: %s", report.status)
        metric_payload = tuple(
            {
                "name": metric.name,
                "value": metric.value,
                "unit": metric.unit,
                "status": metric.status,
            }
            for metric in report.metrics
        )
        self._event_bus.publish(HealthUpdated(status=report.status, metrics=metric_payload))
        for metric in report.metrics:
            self._logger.info(
                "Health metric %s=%.2f%s (%s)",
                metric.name,
                metric.value,
                metric.unit,
                metric.status,
            )

    def _block_until_shutdown(self) -> None:
        if self._cloud_manager is not None:
            self._cloud_manager.join()
            return

        self._supervisor.join_blocking_service(lambda service: service.name == "cloud")

    def _shutdown(self) -> None:
        if self._plugin_manager is not None:
            self._plugin_manager.shutdown()
        self._supervisor.stop_all()
        self._logger.info("All services stopped")