from __future__ import annotations

import threading
from typing import Any

from ottomandevice.plugins.audio.backend import AudioBackendProtocol, default_audio_backend


class MicrophoneDevice:
    """Thread-safe wrapper around a single microphone input stream."""

    def __init__(
        self,
        device_id: int,
        *,
        sample_rate: int,
        channels: int,
        chunk_size: int,
        backend: AudioBackendProtocol | None = None,
    ) -> None:
        self.device_id = device_id
        self._sample_rate = sample_rate
        self._channels = channels
        self._chunk_size = chunk_size
        self._backend = backend or default_audio_backend()
        self._stream: Any | None = None
        self._lock = threading.RLock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._stream is not None

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def channels(self) -> int:
        return self._channels

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    def open(self) -> bool:
        with self._lock:
            if self.is_open:
                return True
            try:
                stream = self._backend.open_input_stream(
                    self.device_id,
                    sample_rate=self._sample_rate,
                    channels=self._channels,
                    chunk_size=self._chunk_size,
                )
                stream.start()
                self._stream = stream
                return True
            except Exception:
                self._stream = None
                return False

    def close(self) -> None:
        with self._lock:
            if self._stream is None:
                return
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None

    def read_chunk(self) -> tuple[Any | None, bool]:
        """Read one PCM chunk. Returns (samples, overflowed)."""
        with self._lock:
            if self._stream is None:
                return None, False
            data, overflowed = self._stream.read(self._chunk_size)
            return data, bool(overflowed)

    def configure(self, *, sample_rate: int, channels: int, chunk_size: int) -> None:
        with self._lock:
            self._sample_rate = sample_rate
            self._channels = channels
            self._chunk_size = chunk_size
            if self.is_open:
                device_id = self.device_id
                self.close()
                self.device_id = device_id
                self.open()
