from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

from ottomandevice.core.health import MetricValue


@dataclass(frozen=True)
class AudioHealthSnapshot:
    """Point-in-time audio input health state."""

    status: str
    connected: bool
    device_id: int | None
    sample_rate: int
    channels: int
    input_level_db: float
    chunks_captured: int
    buffer_overruns: int
    silence_events: int
    last_error: str | None
    last_chunk_age_seconds: float | None


class AudioHealth:
    """Tracks microphone connectivity, levels, and capture quality."""

    def __init__(self, *, sample_rate: int = 16000, channels: int = 1) -> None:
        self._lock = threading.RLock()
        self._sample_rate = sample_rate
        self._channels = channels
        self._connected = False
        self._device_id: int | None = None
        self._chunks_captured = 0
        self._buffer_overruns = 0
        self._silence_events = 0
        self._input_level_db = -100.0
        self._last_error: str | None = None
        self._last_chunk_at: float | None = None

    def set_format(self, *, sample_rate: int, channels: int) -> None:
        with self._lock:
            self._sample_rate = sample_rate
            self._channels = channels

    def set_device(self, device_id: int | None, *, connected: bool) -> None:
        with self._lock:
            self._device_id = device_id
            self._connected = connected

    def record_chunk(
        self,
        *,
        success: bool,
        input_level_db: float,
        silent: bool = False,
        overflowed: bool = False,
    ) -> None:
        with self._lock:
            if success:
                self._chunks_captured += 1
                self._input_level_db = input_level_db
                self._last_chunk_at = time.monotonic()
            if silent:
                self._silence_events += 1
            if overflowed:
                self._buffer_overruns += 1

    def record_disconnect(self) -> None:
        with self._lock:
            self._connected = False

    def record_reconnect(self, device_id: int) -> None:
        with self._lock:
            self._connected = True
            self._device_id = device_id
            self._last_error = None

    def record_error(self, error: str) -> None:
        with self._lock:
            self._last_error = error

    def sync_capture_stats(
        self,
        *,
        chunks_captured: int,
        buffer_overruns: int,
        input_level_db: float,
    ) -> None:
        with self._lock:
            self._chunks_captured = chunks_captured
            self._buffer_overruns = buffer_overruns
            self._input_level_db = input_level_db

    def snapshot(self) -> AudioHealthSnapshot:
        with self._lock:
            last_chunk_age = None
            if self._last_chunk_at is not None:
                last_chunk_age = max(0.0, time.monotonic() - self._last_chunk_at)
            status = self._resolve_status(last_chunk_age)
            return AudioHealthSnapshot(
                status=status,
                connected=self._connected,
                device_id=self._device_id,
                sample_rate=self._sample_rate,
                channels=self._channels,
                input_level_db=self._input_level_db,
                chunks_captured=self._chunks_captured,
                buffer_overruns=self._buffer_overruns,
                silence_events=self._silence_events,
                last_error=self._last_error,
                last_chunk_age_seconds=last_chunk_age,
            )

    def to_metrics(self) -> tuple[tuple[MetricValue, ...], dict[str, Any]]:
        snap = self.snapshot()
        metrics: list[MetricValue] = [
            MetricValue(
                "audio_input_level_db",
                snap.input_level_db,
                "dBFS",
                _metric_status(snap.status),
            ),
            MetricValue(
                "audio_buffer_overruns",
                float(snap.buffer_overruns),
                "events",
                "warn" if snap.buffer_overruns > 0 else "ok",
            ),
        ]
        details = {
            "audio_status": snap.status,
            "audio_connected": snap.connected,
            "audio_device_id": snap.device_id,
            "audio_sample_rate": snap.sample_rate,
            "audio_channels": snap.channels,
            "audio_chunks_captured": snap.chunks_captured,
            "audio_silence_events": snap.silence_events,
            "audio_last_error": snap.last_error,
        }
        return tuple(metrics), details

    def to_cloud_dict(self) -> dict[str, Any]:
        snap = self.snapshot()
        return {
            "status": snap.status,
            "connected": snap.connected,
            "device_id": snap.device_id,
            "sample_rate": snap.sample_rate,
            "channels": snap.channels,
            "input_level_db": snap.input_level_db,
            "chunks_captured": snap.chunks_captured,
            "buffer_overruns": snap.buffer_overruns,
            "silence_events": snap.silence_events,
            "last_error": snap.last_error,
        }

    def _resolve_status(self, last_chunk_age: float | None) -> str:
        if not self._connected:
            return "disconnected"
        if self._last_error:
            return "error"
        if self._buffer_overruns > 0:
            return "warn"
        if last_chunk_age is not None and last_chunk_age > 2.0:
            return "warn"
        return "ok"


def _metric_status(status: str) -> str:
    if status in {"error", "disconnected"}:
        return "warn"
    if status == "warn":
        return "warn"
    return "ok"
