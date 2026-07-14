from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionContext:
    """Mutable state for a single digital-human interaction session."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ai_session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    camera_frame_number: int = 0
    transcript: str = ""
    ai_response: str = ""
    pipeline_stage: str = "idle"
    started_at: float = field(default_factory=time.perf_counter)
    last_activity_at: float = field(default_factory=time.perf_counter)
    metadata: dict[str, Any] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def touch(self) -> None:
        with self._lock:
            self.last_activity_at = time.perf_counter()

    def set_stage(self, stage: str) -> None:
        with self._lock:
            self.pipeline_stage = stage
            self.last_activity_at = time.perf_counter()

    def idle_seconds(self) -> float:
        with self._lock:
            return time.perf_counter() - self.last_activity_at

    def duration_seconds(self) -> float:
        with self._lock:
            return time.perf_counter() - self.started_at

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.session_id,
                "ai_session_id": self.ai_session_id,
                "camera_frame_number": self.camera_frame_number,
                "transcript": self.transcript,
                "ai_response": self.ai_response,
                "pipeline_stage": self.pipeline_stage,
                "duration_seconds": round(self.duration_seconds(), 3),
                "idle_seconds": round(self.idle_seconds(), 3),
                "metadata": dict(self.metadata),
            }
