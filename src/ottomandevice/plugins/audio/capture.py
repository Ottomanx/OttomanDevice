from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

import numpy as np

from ottomandevice.plugins.audio.device import MicrophoneDevice

ChunkCallback = Callable[[bytes, int], None]


@dataclass(frozen=True)
class ChunkResult:
    """Result of a single PCM capture attempt."""

    success: bool
    pcm: bytes | None
    chunk_number: int
    sample_rate: int
    channels: int
    input_level_db: float
    silent: bool
    overflowed: bool
    streaming: bool = False


def pcm_to_bytes(samples: Any) -> bytes:
    array = np.asarray(samples)
    if array.dtype != np.int16:
        array = np.clip(array, -1.0, 1.0)
        array = (array * 32767.0).astype(np.int16)
    return array.tobytes()


def compute_input_level_db(samples: Any) -> float:
    array = np.asarray(samples, dtype=np.float64)
    if array.size == 0:
        return -100.0
    if np.issubdtype(np.asarray(samples).dtype, np.integer):
        array = array / 32768.0
    rms = float(np.sqrt(np.mean(array * array)))
    if rms <= 1e-10:
        return -100.0
    return 20.0 * float(np.log10(rms))


class AudioCapture:
    """PCM capture, streaming, silence detection, and overrun tracking."""

    def __init__(
        self,
        device: MicrophoneDevice,
        *,
        silence_threshold_db: float = -40.0,
    ) -> None:
        self._device = device
        self._silence_threshold_db = silence_threshold_db
        self._lock = threading.RLock()
        self._streaming = False
        self._stream_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._chunk_count = 0
        self._buffer_overruns = 0
        self._latest_pcm: bytes | None = None
        self._latest_level_db = -100.0
        self._chunk_callback: ChunkCallback | None = None
        self._on_chunk_event: Callable[[ChunkResult], None] | None = None

    @property
    def chunk_count(self) -> int:
        with self._lock:
            return self._chunk_count

    @property
    def buffer_overruns(self) -> int:
        with self._lock:
            return self._buffer_overruns

    @property
    def latest_level_db(self) -> float:
        with self._lock:
            return self._latest_level_db

    @property
    def is_streaming(self) -> bool:
        with self._lock:
            return self._streaming

    @property
    def latest_pcm(self) -> bytes | None:
        with self._lock:
            return self._latest_pcm

    def set_chunk_callback(self, callback: ChunkCallback | None) -> None:
        with self._lock:
            self._chunk_callback = callback

    def set_chunk_event_handler(self, handler: Callable[[ChunkResult], None] | None) -> None:
        with self._lock:
            self._on_chunk_event = handler

    def read_single(self) -> ChunkResult:
        samples, overflowed = self._device.read_chunk()
        result = self._build_result(samples, overflowed=overflowed, streaming=False)
        self._record_chunk(result)
        return result

    def start_stream(self) -> None:
        with self._lock:
            if self._streaming:
                return
            self._stop_event.clear()
            self._streaming = True
            self._stream_thread = threading.Thread(
                target=self._stream_loop,
                name=f"audio-stream-{self._device.device_id}",
                daemon=True,
            )
            self._stream_thread.start()

    def stop_stream(self) -> None:
        with self._lock:
            if not self._streaming:
                return
            self._stop_event.set()
            thread = self._stream_thread
            self._streaming = False
        if thread is not None and thread.is_alive():
            thread.join(timeout=5.0)
        with self._lock:
            self._stream_thread = None

    def reset_counters(self) -> None:
        with self._lock:
            self._chunk_count = 0
            self._buffer_overruns = 0

    def _stream_loop(self) -> None:
        interval = self._device.chunk_size / max(self._device.sample_rate, 1)
        while not self._stop_event.is_set():
            loop_start = time.monotonic()
            samples, overflowed = self._device.read_chunk()
            result = self._build_result(samples, overflowed=overflowed, streaming=True)
            self._record_chunk(result)
            elapsed = time.monotonic() - loop_start
            sleep_for = max(0.0, interval - elapsed)
            if self._stop_event.wait(sleep_for):
                break

    def _build_result(
        self,
        samples: Any | None,
        *,
        overflowed: bool,
        streaming: bool,
    ) -> ChunkResult:
        success = samples is not None
        pcm = pcm_to_bytes(samples) if success else None
        level_db = compute_input_level_db(samples) if success else -100.0
        silent = success and level_db <= self._silence_threshold_db
        with self._lock:
            chunk_number = self._chunk_count + 1
            if overflowed:
                self._buffer_overruns += 1
        return ChunkResult(
            success=success,
            pcm=pcm,
            chunk_number=chunk_number,
            sample_rate=self._device.sample_rate,
            channels=self._device.channels,
            input_level_db=round(level_db, 2),
            silent=silent,
            overflowed=overflowed,
            streaming=streaming,
        )

    def _record_chunk(self, result: ChunkResult) -> None:
        handler: Callable[[ChunkResult], None] | None
        callback: ChunkCallback | None
        with self._lock:
            if result.success and result.pcm is not None:
                self._chunk_count += 1
                self._latest_pcm = result.pcm
                self._latest_level_db = result.input_level_db
            handler = self._on_chunk_event
            callback = self._chunk_callback
            pcm = self._latest_pcm
            chunk_number = self._chunk_count
        if handler is not None:
            handler(result)
        if callback is not None and result.success and pcm is not None:
            callback(pcm, chunk_number)
