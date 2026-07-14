from __future__ import annotations

import struct
import threading


class VoiceActivityDetector:
    """Simple RMS-based voice activity detector for PCM int16 audio."""

    def __init__(self, *, threshold_db: float = -35.0, hangover_chunks: int = 3) -> None:
        self._threshold_db = threshold_db
        self._hangover = hangover_chunks
        self._silence_count = 0
        self._speech_active = False
        self._lock = threading.RLock()

    @property
    def is_speech_active(self) -> bool:
        with self._lock:
            return self._speech_active

    def process(self, pcm: bytes) -> bool:
        level_db = self._level_db(pcm)
        with self._lock:
            if level_db >= self._threshold_db:
                self._speech_active = True
                self._silence_count = 0
                return True
            if self._speech_active:
                self._silence_count += 1
                if self._silence_count >= self._hangover:
                    self._speech_active = False
            return self._speech_active

    def reset(self) -> None:
        with self._lock:
            self._speech_active = False
            self._silence_count = 0

    @staticmethod
    def _level_db(pcm: bytes) -> float:
        if len(pcm) < 2:
            return -100.0
        count = len(pcm) // 2
        samples = struct.unpack(f"<{count}h", pcm[: count * 2])
        if not samples:
            return -100.0
        rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5
        if rms <= 1.0:
            return -100.0
        import math

        return 20.0 * math.log10(rms / 32768.0)
