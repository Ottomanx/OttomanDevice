from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from ottomandevice.core.exceptions import ExceptionManager, ServiceError
from ottomandevice.core.logger import get_logger
from ottomandevice.core.event_bus import (
    EventBus,
    ServiceFailed,
    ServiceStarted,
    ServiceStopped,
)
from ottomandevice.core.performance import PerformanceMonitor


class ServiceState(str, Enum):
    """Lifecycle states for managed services."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    FAILED = "failed"


class BaseService(ABC):
    """Abstract base class for all OttomanDevice runtime services."""

    def __init__(
        self,
        name: str,
        *,
        required: bool = False,
        restartable: bool = True,
        event_bus: EventBus | None = None,
    ) -> None:
        self._name = name
        self._required = required
        self._restartable = restartable
        self._state = ServiceState.STOPPED
        self._logger = get_logger(f"service.{name}")
        self._exceptions = ExceptionManager.get_instance()
        self._performance = PerformanceMonitor.get_instance()
        self._event_bus = event_bus or EventBus.get_instance()

    @property
    def name(self) -> str:
        """Return the service name."""
        return self._name

    @property
    def required(self) -> bool:
        """Return whether the service is required for runtime startup."""
        return self._required

    @property
    def restartable(self) -> bool:
        """Return whether the supervisor may restart this service."""
        return self._restartable

    @property
    def state(self) -> ServiceState:
        """Return the current service lifecycle state."""
        return self._state

    def start(self) -> None:
        """Start the service and transition lifecycle state."""
        if self._state == ServiceState.RUNNING:
            return

        self._state = ServiceState.STARTING
        try:
            with self._performance.measure(f"service.{self._name}.start"):
                self.on_start()
        except Exception as exc:
            self._state = ServiceState.FAILED
            self._exceptions.report(exc, service=self._name, context="start")
            self._logger.exception("Service failed to start")
            self._event_bus.publish(
                ServiceFailed(
                    service_name=self._name,
                    error=str(exc),
                    context="start",
                )
            )
            raise ServiceError(f"{self._name} failed to start") from exc

        self._state = ServiceState.RUNNING
        self._logger.info("Service started")
        self._event_bus.publish(ServiceStarted(service_name=self._name))

    def stop(self) -> None:
        """Stop the service and transition lifecycle state."""
        if self._state in {ServiceState.STOPPED, ServiceState.STOPPING}:
            return

        self._state = ServiceState.STOPPING
        try:
            with self._performance.measure(f"service.{self._name}.stop"):
                self.on_stop()
        except Exception as exc:
            self._state = ServiceState.FAILED
            self._exceptions.report(exc, service=self._name, context="stop")
            self._logger.exception("Service failed to stop")
            self._event_bus.publish(
                ServiceFailed(
                    service_name=self._name,
                    error=str(exc),
                    context="stop",
                )
            )
            raise ServiceError(f"{self._name} failed to stop") from exc

        self._state = ServiceState.STOPPED
        self._logger.info("Service stopped")
        self._event_bus.publish(ServiceStopped(service_name=self._name))

    def health(self) -> dict[str, Any]:
        """Return service-specific health information."""
        return {
            "name": self._name,
            "state": self._state.value,
            "required": self._required,
            "restartable": self._restartable,
        }

    @abstractmethod
    def on_start(self) -> None:
        """Start service-specific resources."""

    @abstractmethod
    def on_stop(self) -> None:
        """Stop service-specific resources."""


class LegacyServiceAdapter(BaseService):
    """Adapter that wraps legacy start/stop services into BaseService."""

    def __init__(
        self,
        name: str,
        service: Any,
        *,
        required: bool = False,
        restartable: bool = True,
    ) -> None:
        super().__init__(name, required=required, restartable=restartable)
        self._service = service

    @property
    def wrapped(self) -> Any:
        """Return the wrapped legacy service instance."""
        return self._service

    def on_start(self) -> None:
        start = getattr(self._service, "start", None)
        if not callable(start):
            raise ServiceError(f"{self._name} has no start() method")
        start()

    def on_stop(self) -> None:
        stop = getattr(self._service, "stop", None)
        if callable(stop):
            stop()

    def join(self) -> None:
        """Block on the wrapped service join() method when available."""
        join = getattr(self._service, "join", None)
        if callable(join):
            join()

    def health(self) -> dict[str, Any]:
        payload = super().health()
        payload["adapter"] = type(self._service).__name__
        return payload
