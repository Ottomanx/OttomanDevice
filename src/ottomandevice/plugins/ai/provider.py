from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AIMessage:
    """Single message in a conversation turn."""

    role: str
    content: str


@dataclass(frozen=True)
class AIResponse:
    """Completed provider response."""

    text: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class AIStreamChunk:
    """Incremental streamed response chunk."""

    text: str
    done: bool = False
    provider: str = ""


@dataclass
class ProviderMetrics:
    """Runtime metrics for a single provider."""

    requests: int = 0
    failures: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0

    @property
    def average_latency_ms(self) -> float:
        if self.requests == 0:
            return 0.0
        return self.total_latency_ms / self.requests


class AIProvider(ABC):
    """Abstract AI inference provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider identifier."""

    @property
    @abstractmethod
    def model(self) -> str:
        """Return the default model name."""

    @abstractmethod
    async def connect(self) -> None:
        """Validate credentials and establish connectivity."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Release provider resources."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Return whether the provider can accept requests."""

    @abstractmethod
    async def complete(
        self,
        messages: tuple[AIMessage, ...],
        *,
        model: str | None = None,
    ) -> AIResponse:
        """Generate a full completion."""

    @abstractmethod
    async def stream(
        self,
        messages: tuple[AIMessage, ...],
        *,
        model: str | None = None,
    ) -> AsyncIterator[AIStreamChunk]:
        """Stream a completion incrementally."""
        yield AIStreamChunk(text="", done=True, provider=self.name)
