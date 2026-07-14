from __future__ import annotations

import threading
from enum import Enum

from ottomandevice.plugins.avatar.state import AvatarState


class Emotion(str, Enum):
    """Avatar facial emotion presets."""

    NEUTRAL = "neutral"
    HAPPY = "happy"
    CONCERNED = "concerned"
    THINKING = "thinking"
    SPEAKING = "speaking"
    SLEEPY = "sleepy"


_STATE_EMOTION: dict[AvatarState, Emotion] = {
    AvatarState.BOOTING: Emotion.NEUTRAL,
    AvatarState.IDLE: Emotion.NEUTRAL,
    AvatarState.LISTENING: Emotion.HAPPY,
    AvatarState.THINKING: Emotion.THINKING,
    AvatarState.SPEAKING: Emotion.SPEAKING,
    AvatarState.ERROR: Emotion.CONCERNED,
    AvatarState.SLEEPING: Emotion.SLEEPY,
}


_BLEND_SHAPES: dict[Emotion, dict[str, float]] = {
    Emotion.NEUTRAL: {"brow_raise": 0.0, "smile": 0.0, "eye_wide": 0.0},
    Emotion.HAPPY: {"brow_raise": 0.1, "smile": 0.7, "eye_wide": 0.2},
    Emotion.CONCERNED: {"brow_raise": 0.6, "smile": 0.0, "eye_wide": 0.3},
    Emotion.THINKING: {"brow_raise": 0.4, "smile": 0.0, "eye_wide": 0.1},
    Emotion.SPEAKING: {"brow_raise": 0.1, "smile": 0.2, "eye_wide": 0.1},
    Emotion.SLEEPY: {"brow_raise": 0.0, "smile": 0.0, "eye_wide": -0.3},
}


class EmotionEngine:
    """Maps runtime context to avatar emotions and blend shapes."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._override: Emotion | None = None

    @property
    def emotion(self) -> Emotion:
        with self._lock:
            if self._override is not None:
                return self._override
            return Emotion.NEUTRAL

    def set_override(self, emotion: Emotion | None) -> None:
        with self._lock:
            self._override = emotion

    def map_state(self, state: AvatarState) -> Emotion:
        with self._lock:
            if self._override is not None:
                return self._override
            return _STATE_EMOTION.get(state, Emotion.NEUTRAL)

    def blend_shapes(self, emotion: Emotion | None = None) -> dict[str, float]:
        target = emotion or self.emotion
        return dict(_BLEND_SHAPES.get(target, _BLEND_SHAPES[Emotion.NEUTRAL]))
