from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field


WakeWordCallback = Callable[[str], None]


@dataclass
class WakeWordRegistration:
    """Registered wake word phrase and callback."""

    phrase: str
    callback: WakeWordCallback


class WakeWordFramework:
    """Framework for wake word detection hooks (extensible, no ML model bundled)."""

    def __init__(self) -> None:
        self._registrations: list[WakeWordRegistration] = []
        self._lock = threading.RLock()
        self._enabled = False

    @property
    def enabled(self) -> bool:
        with self._lock:
            return self._enabled

    def enable(self) -> None:
        with self._lock:
            self._enabled = True

    def disable(self) -> None:
        with self._lock:
            self._enabled = False

    def register(self, phrase: str, callback: WakeWordCallback) -> None:
        with self._lock:
            self._registrations.append(WakeWordRegistration(phrase=phrase.lower(), callback=callback))

    def unregister_all(self) -> None:
        with self._lock:
            self._registrations.clear()

    def process_transcript(self, text: str) -> bool:
        """Match final transcripts against registered wake word phrases."""
        with self._lock:
            if not self._enabled or not text:
                return False
            lowered = text.lower()
            for registration in self._registrations:
                if registration.phrase in lowered:
                    registration.callback(registration.phrase)
                    return True
            return False
