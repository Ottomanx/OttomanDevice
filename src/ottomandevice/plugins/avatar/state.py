from __future__ import annotations

import threading
from enum import Enum
from typing import Callable


class AvatarState(str, Enum):
    """High-level avatar lifecycle states."""

    BOOTING = "booting"
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    ERROR = "error"
    SLEEPING = "sleeping"


_TRANSITIONS: dict[AvatarState, frozenset[AvatarState]] = {
    AvatarState.BOOTING: frozenset({AvatarState.IDLE, AvatarState.ERROR}),
    AvatarState.IDLE: frozenset(
        {
            AvatarState.LISTENING,
            AvatarState.THINKING,
            AvatarState.SPEAKING,
            AvatarState.SLEEPING,
            AvatarState.ERROR,
        }
    ),
    AvatarState.LISTENING: frozenset({AvatarState.THINKING, AvatarState.IDLE, AvatarState.ERROR}),
    AvatarState.THINKING: frozenset({AvatarState.SPEAKING, AvatarState.IDLE, AvatarState.ERROR}),
    AvatarState.SPEAKING: frozenset({AvatarState.IDLE, AvatarState.LISTENING, AvatarState.ERROR}),
    AvatarState.ERROR: frozenset({AvatarState.IDLE, AvatarState.BOOTING}),
    AvatarState.SLEEPING: frozenset({AvatarState.IDLE, AvatarState.LISTENING, AvatarState.ERROR}),
}


StateChangeCallback = Callable[[AvatarState, AvatarState, str], None]


class AvatarStateMachine:
    """Thread-safe avatar state machine with validated transitions."""

    def __init__(
        self,
        *,
        initial: AvatarState = AvatarState.BOOTING,
        on_change: StateChangeCallback | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._state = initial
        self._on_change = on_change

    @property
    def state(self) -> AvatarState:
        with self._lock:
            return self._state

    def can_transition(self, target: AvatarState) -> bool:
        with self._lock:
            allowed = _TRANSITIONS.get(self._state, frozenset())
            return target in allowed or target == self._state

    def transition(self, target: AvatarState, *, reason: str = "") -> bool:
        with self._lock:
            if target == self._state:
                return True
            allowed = _TRANSITIONS.get(self._state, frozenset())
            if target not in allowed:
                return False
            previous = self._state
            self._state = target
        if self._on_change is not None:
            self._on_change(previous, target, reason)
        return True

    def force(self, target: AvatarState, *, reason: str = "") -> None:
        with self._lock:
            previous = self._state
            if previous == target:
                return
            self._state = target
        if self._on_change is not None:
            self._on_change(previous, target, reason)
