from __future__ import annotations

import struct
import threading
from dataclasses import dataclass


@dataclass(frozen=True)
class LipSyncFrame:
    """Mouth pose derived from audio analysis."""

    mouth_openness: float
    viseme: str = "neutral"


class LipSyncEngine:
    """Derives lip-sync frames from PCM audio without external models."""

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._lock = threading.RLock()
        self._last_frame = LipSyncFrame(mouth_openness=0.0)

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        with self._lock:
            self._enabled = enabled

    @property
    def last_frame(self) -> LipSyncFrame:
        with self._lock:
            return self._last_frame

    def analyze_pcm(self, pcm: bytes) -> LipSyncFrame:
        if not pcm:
            frame = LipSyncFrame(mouth_openness=0.0, viseme="neutral")
            with self._lock:
                self._last_frame = frame
            return frame

        level = self._rms(pcm)
        openness = min(1.0, max(0.0, level * 8.0))
        viseme = self._viseme_for_openness(openness)
        frame = LipSyncFrame(mouth_openness=openness, viseme=viseme)
        with self._lock:
            self._last_frame = frame
        return frame

    @staticmethod
    def _rms(pcm: bytes) -> float:
        if len(pcm) < 2:
            return 0.0
        count = len(pcm) // 2
        samples = struct.unpack(f"<{count}h", pcm[: count * 2])
        if not samples:
            return 0.0
        rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5
        return rms / 32768.0

    @staticmethod
    def _viseme_for_openness(openness: float) -> str:
        if openness < 0.05:
            return "neutral"
        if openness < 0.25:
            return "aa"
        if openness < 0.5:
            return "oh"
        if openness < 0.75:
            return "ou"
        return "wide"
