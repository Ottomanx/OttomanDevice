from __future__ import annotations

import threading
import time
from typing import Callable

from ottomandevice.core.event_bus import EventBus, ServiceFailed
from ottomandevice.core.exceptions import ExceptionManager, ServiceError
from ottomandevice.core.logger import get_logger
from ottomandevice.core.service import BaseService, ServiceState


class ServiceSupervisor:
    """Starts, stops, and restarts managed runtime services."""

    def __init__(
        self,
        *,
        restart_delay_seconds: float = 5.0,
        max_restarts: int = 10,
        event_bus: EventBus | None = None,
    ) -> None:
        self._services: list[BaseService] = []
        self._restart_delay_seconds = restart_delay_seconds
        self._max_restarts = max_restarts
        self._restart_counts: dict[str, int] = {}
        self._stop_event = threading.Event()
        self._supervisor_thread: threading.Thread | None = None
        self._exceptions = ExceptionManager.get_instance()
        self._logger = get_logger("supervisor")
        self._event_bus = event_bus or EventBus.get_instance()

    def register(self, service: BaseService) -> None:
        """Register a service with the supervisor."""
        self._services.append(service)

    @property
    def services(self) -> list[BaseService]:
        """Return registered services."""
        return list(self._services)

    def start_all(self) -> None:
        """Start all registered services."""
        for service in self._services:
            self._start_service(service, required=service.required)

    def stop_all(self) -> None:
        """Stop all registered services in reverse registration order."""
        self._stop_event.set()
        if self._supervisor_thread and self._supervisor_thread.is_alive():
            self._supervisor_thread.join(timeout=self._restart_delay_seconds + 1)

        for service in reversed(self._services):
            if service.state == ServiceState.RUNNING:
                try:
                    service.stop()
                except ServiceError as exc:
                    self._logger.warning("Failed to stop %s: %s", service.name, exc)

    def start_service(self, name: str) -> None:
        """Start a single registered service by name."""
        service = self._find_service(name)
        self._start_service(service, required=service.required)

    def stop_service(self, name: str) -> None:
        """Stop a single registered service by name."""
        service = self._find_service(name)
        if service.state == ServiceState.RUNNING:
            service.stop()

    def restart_service(self, name: str) -> None:
        """Restart a registered service by name."""
        service = self._find_service(name)
        if service.state == ServiceState.RUNNING:
            service.stop()
        self._start_service(service, required=service.required)

    def supervise(self, *, poll_interval_seconds: float = 1.0) -> None:
        """Run a background supervision loop that restarts failed services."""
        if self._supervisor_thread and self._supervisor_thread.is_alive():
            return

        self._stop_event.clear()
        self._supervisor_thread = threading.Thread(
            target=self._supervision_loop,
            kwargs={"poll_interval_seconds": poll_interval_seconds},
            name="service-supervisor",
            daemon=True,
        )
        self._supervisor_thread.start()

    def join_blocking_service(self, predicate: Callable[[BaseService], bool]) -> None:
        """Block until shutdown on the first matching service that supports join()."""
        for service in self._services:
            if not predicate(service):
                continue
            join = getattr(service, "join", None)
            if callable(join):
                join()
                return

    def _supervision_loop(self, *, poll_interval_seconds: float) -> None:
        while not self._stop_event.wait(poll_interval_seconds):
            for service in self._services:
                if not service.restartable:
                    continue
                if service.state != ServiceState.FAILED:
                    continue

                restarts = self._restart_counts.get(service.name, 0)
                if restarts >= self._max_restarts:
                    self._logger.error(
                        "Service %s exceeded max restarts (%s)",
                        service.name,
                        self._max_restarts,
                    )
                    self._event_bus.publish(
                        ServiceFailed(
                            service_name=service.name,
                            error="max restarts exceeded",
                            context="supervisor",
                        )
                    )
                    continue

                self._logger.warning("Restarting failed service %s", service.name)
                time.sleep(self._restart_delay_seconds)
                try:
                    self._start_service(service, required=False)
                    self._restart_counts[service.name] = restarts + 1
                except ServiceError as exc:
                    self._exceptions.report(exc, service=service.name, context="restart")
                    self._event_bus.publish(
                        ServiceFailed(
                            service_name=service.name,
                            error=str(exc),
                            context="restart",
                        )
                    )
                    self._logger.exception("Automatic restart failed for %s", service.name)

    def _start_service(self, service: BaseService, *, required: bool) -> None:
        try:
            service.start()
        except ServiceError:
            if required:
                raise
            self._logger.warning("Optional service %s failed to start", service.name)

    def _find_service(self, name: str) -> BaseService:
        for service in self._services:
            if service.name == name:
                return service
        raise ServiceError(f"Service not registered: {name}")
