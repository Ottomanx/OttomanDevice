from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from typing import Any, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


@dataclass(frozen=True)
class TimingSample:
    """Single performance timing measurement."""

    name: str
    duration_ms: float
    timestamp: float


@dataclass
class TimingStats:
    """Aggregated timing statistics for a named operation."""

    name: str
    count: int = 0
    total_ms: float = 0.0
    min_ms: float = field(default=float("inf"))
    max_ms: float = 0.0

    @property
    def average_ms(self) -> float:
        """Return the average duration in milliseconds."""
        if self.count == 0:
            return 0.0
        return self.total_ms / self.count


class PerformanceMonitor:
    """Collects execution timing metrics for runtime operations."""

    _instance: PerformanceMonitor | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._samples: list[TimingSample] = []
        self._stats: dict[str, TimingStats] = {}

    @classmethod
    def get_instance(cls) -> PerformanceMonitor:
        """Return the process-wide performance monitor singleton."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def record(self, name: str, duration_ms: float) -> TimingSample:
        """Record a timing sample and update aggregate statistics."""
        sample = TimingSample(name=name, duration_ms=duration_ms, timestamp=time.time())
        self._samples.append(sample)

        stats = self._stats.setdefault(name, TimingStats(name=name))
        stats.count += 1
        stats.total_ms += duration_ms
        stats.min_ms = min(stats.min_ms, duration_ms)
        stats.max_ms = max(stats.max_ms, duration_ms)
        return sample

    @contextmanager
    def measure(self, name: str) -> Iterator[None]:
        """Context manager that records execution time for a code block."""
        started = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            self.record(name, elapsed_ms)

    def timed(self, name: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorator that records function execution time."""

        def decorator(func: Callable[P, R]) -> Callable[P, R]:
            metric_name = name or func.__qualname__

            @wraps(func)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                with self.measure(metric_name):
                    return func(*args, **kwargs)

            return wrapper

        return decorator

    def stats(self, name: str | None = None) -> dict[str, TimingStats]:
        """Return aggregate timing statistics."""
        if name is None:
            return dict(self._stats)
        stats = self._stats.get(name)
        return {name: stats} if stats is not None else {}

    def samples(self, name: str | None = None) -> list[TimingSample]:
        """Return recorded timing samples."""
        if name is None:
            return list(self._samples)
        return [sample for sample in self._samples if sample.name == name]

    def clear(self) -> None:
        """Clear all recorded samples and statistics."""
        self._samples.clear()
        self._stats.clear()
