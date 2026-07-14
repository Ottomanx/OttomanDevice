from __future__ import annotations

from abc import ABC, abstractmethod


class BandwidthLimiter(ABC):
    """Interface for transfer rate limiting. No-op by default in Sprint 39."""

    @abstractmethod
    async def acquire(self, nbytes: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def report(self, nbytes: int) -> None:
        """Report bytes transferred for adaptive limiters."""
        raise NotImplementedError


class NoOpBandwidthLimiter(BandwidthLimiter):
    async def acquire(self, nbytes: int) -> None:
        del nbytes

    async def report(self, nbytes: int) -> None:
        del nbytes
