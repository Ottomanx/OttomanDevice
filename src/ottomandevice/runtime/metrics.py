from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class SessionMetrics:
    """Pipeline latency and session health metrics."""

    stt_latency_ms: float = 0.0
    ai_latency_ms: float = 0.0
    tts_latency_ms: float = 0.0
    avatar_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    session_duration_ms: float = 0.0
    pipeline_stage: str = "idle"
    interactions_completed: int = 0
    recoveries: int = 0
    failures: int = 0
    started_at: float = field(default_factory=time.perf_counter)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def record_interaction(
        self,
        *,
        stt_ms: float,
        ai_ms: float,
        tts_ms: float,
        avatar_ms: float = 0.0,
    ) -> None:
        with self._lock:
            self.stt_latency_ms = stt_ms
            self.ai_latency_ms = ai_ms
            self.tts_latency_ms = tts_ms
            self.avatar_latency_ms = avatar_ms
            self.total_latency_ms = stt_ms + ai_ms + tts_ms + avatar_ms
            self.interactions_completed += 1

    def record_failure(self) -> None:
        with self._lock:
            self.failures += 1

    def record_recovery(self) -> None:
        with self._lock:
            self.recoveries += 1

    def set_stage(self, stage: str) -> None:
        with self._lock:
            self.pipeline_stage = stage

    def finalize(self) -> None:
        with self._lock:
            self.session_duration_ms = (time.perf_counter() - self.started_at) * 1000

    def to_dict(self) -> dict[str, float | int | str]:
        with self._lock:
            return {
                "stt_latency_ms": round(self.stt_latency_ms, 2),
                "ai_latency_ms": round(self.ai_latency_ms, 2),
                "tts_latency_ms": round(self.tts_latency_ms, 2),
                "avatar_latency_ms": round(self.avatar_latency_ms, 2),
                "total_latency_ms": round(self.total_latency_ms, 2),
                "session_duration_ms": round(self.session_duration_ms, 2),
                "pipeline_stage": self.pipeline_stage,
                "interactions_completed": self.interactions_completed,
                "recoveries": self.recoveries,
                "failures": self.failures,
            }
