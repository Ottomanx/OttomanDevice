from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field

from ottomandevice.plugins.ai.provider import AIMessage


@dataclass
class AIConversation:
    """Thread-safe conversation history with bounded memory."""

    session_id: str
    max_messages: int = 20
    _messages: list[AIMessage] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    @classmethod
    def create(cls, *, max_messages: int = 20, session_id: str | None = None) -> AIConversation:
        return cls(session_id=session_id or str(uuid.uuid4()), max_messages=max_messages)

    def add_message(self, role: str, content: str) -> None:
        with self._lock:
            self._messages.append(AIMessage(role=role, content=content))
            self._trim_history()

    def get_messages(self) -> tuple[AIMessage, ...]:
        with self._lock:
            return tuple(self._messages)

    def clear(self) -> None:
        with self._lock:
            self._messages.clear()

    def trim_to_window(self, max_messages: int | None = None) -> None:
        limit = max_messages if max_messages is not None else self.max_messages
        with self._lock:
            self.max_messages = max(limit, 1)
            self._trim_history()

    def _trim_history(self) -> None:
        overflow = len(self._messages) - self.max_messages
        if overflow > 0:
            del self._messages[:overflow]
