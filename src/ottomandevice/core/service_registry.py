from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

from ottomandevice.core.service import LegacyServiceAdapter
from ottomandevice.core.supervisor import ServiceSupervisor


@runtime_checkable
class ManagedService(Protocol):
    """Protocol for services that expose a start() method."""

    def start(self) -> None: ...


@runtime_checkable
class StoppableService(ManagedService, Protocol):
    """Protocol for services that expose start() and stop() methods."""

    def stop(self) -> None: ...


def _service_name(service: Any) -> str:
    explicit = getattr(service, "name", None)
    if isinstance(explicit, str) and explicit:
        return explicit

    class_name = type(service).__name__
    if class_name.endswith("Service"):
        class_name = class_name[: -len("Service")]
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
    return snake or "service"


class ServiceRegistry:
    """Backward-compatible service registry backed by ServiceSupervisor."""

    def __init__(self) -> None:
        self._supervisor = ServiceSupervisor()

    @property
    def supervisor(self) -> ServiceSupervisor:
        """Return the underlying service supervisor."""
        return self._supervisor

    def register(self, service: ManagedService | Any) -> None:
        """Register a legacy service with the runtime supervisor."""
        self._supervisor.register(
            LegacyServiceAdapter(_service_name(service), service, restartable=True)
        )

    def start_all(self) -> None:
        """Start all registered services."""
        self._supervisor.start_all()

    def stop_all(self) -> None:
        """Stop all registered services."""
        self._supervisor.stop_all()
