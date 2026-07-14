from __future__ import annotations

import threading
from collections import deque


class AudioBuffer:
    """Thread-safe PCM ring buffer for streaming speech input."""

    def __init__(self, *, max_bytes: int = 1024 * 256) -> None:
        self._max_bytes = max_bytes
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._lock = threading.RLock()

    @property
    def size(self) -> int:
        with self._lock:
            return self._size

    def append(self, pcm: bytes) -> None:
        if not pcm:
            return
        with self._lock:
            self._chunks.append(pcm)
            self._size += len(pcm)
            while self._size > self._max_bytes and self._chunks:
                removed = self._chunks.popleft()
                self._size -= len(removed)

    def drain(self) -> bytes:
        with self._lock:
            if not self._chunks:
                return b""
            data = b"".join(self._chunks)
            self._chunks.clear()
            self._size = 0
            return data

    def clear(self) -> None:
        with self._lock:
            self._chunks.clear()
            self._size = 0
