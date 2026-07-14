from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone


class OttomanDeviceError(Exception):
    """Base exception for OttomanDevice runtime errors."""


class ConfigurationError(OttomanDeviceError):
    """Raised when configuration is invalid or missing."""


class ServiceError(OttomanDeviceError):
    """Raised when a managed service fails to start, stop, or run."""


class HealthCheckError(OttomanDeviceError):
    """Raised when a health probe fails."""


class PluginError(OttomanDeviceError):
    """Raised when plugin discovery or lifecycle operations fail."""


@dataclass(frozen=True)
class ExceptionRecord:
    """Immutable record of a reported runtime exception."""

    service: str
    message: str
    exception_type: str
    traceback: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ExceptionManager:
    """Centralized exception reporting for all runtime services."""

    _instance: ExceptionManager | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._records: list[ExceptionRecord] = []

    @classmethod
    def get_instance(cls) -> ExceptionManager:
        """Return the process-wide exception manager singleton."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def report(
        self,
        exc: BaseException,
        *,
        service: str = "runtime",
        context: str | None = None,
    ) -> ExceptionRecord:
        """Capture and store an exception report.

        Args:
            exc: The exception that occurred.
            service: Name of the service that reported the failure.
            context: Optional human-readable context.

        Returns:
            The stored exception record.
        """
        message = str(exc)
        if context:
            message = f"{context}: {message}"

        record = ExceptionRecord(
            service=service,
            message=message,
            exception_type=type(exc).__name__,
            traceback="".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
        )
        self._records.append(record)
        return record

    def records(self) -> list[ExceptionRecord]:
        """Return all captured exception records."""
        return list(self._records)

    def latest(self, service: str | None = None) -> ExceptionRecord | None:
        """Return the most recent exception record, optionally filtered by service."""
        if service is None:
            return self._records[-1] if self._records else None

        for record in reversed(self._records):
            if record.service == service:
                return record
        return None

    def clear(self) -> None:
        """Clear all stored exception records."""
        self._records.clear()
