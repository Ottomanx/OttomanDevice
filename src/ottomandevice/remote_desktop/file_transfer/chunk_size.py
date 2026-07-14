from __future__ import annotations

from abc import ABC, abstractmethod


class ChunkSizeStrategy(ABC):
    """Chunk sizing policy. Fixed in Sprint 39; adaptive in Sprint 39.5."""

    @abstractmethod
    def chunk_size(self) -> int:
        raise NotImplementedError

    def on_chunk_sent(self, nbytes: int, elapsed_ms: float) -> None:
        del nbytes, elapsed_ms


class FixedChunkSizeStrategy(ChunkSizeStrategy):
    def __init__(self, chunk_size: int) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._chunk_size = chunk_size

    def chunk_size(self) -> int:
        return self._chunk_size
