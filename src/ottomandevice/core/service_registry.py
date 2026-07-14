from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ManagedService(Protocol):
    def start(self) -> None: ...


@runtime_checkable
class StoppableService(ManagedService, Protocol):
    def stop(self) -> None: ...


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: list[Any] = []

    def register(self, service: ManagedService | Any) -> None:
        self._services.append(service)

    def start_all(self) -> None:
        for service in self._services:
            start = getattr(service, "start", None)
            if callable(start):
                start()

    def stop_all(self) -> None:
        for service in reversed(self._services):
            stop = getattr(service, "stop", None)
            if callable(stop):
                stop()
