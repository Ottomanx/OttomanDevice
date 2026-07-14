from __future__ import annotations

from enum import Enum
from typing import Final
from uuid import uuid4

from ottomandevice.logging import get_logger

logger = get_logger("remote_desktop.session")


class SessionState(str, Enum):
    IDLE = "IDLE"
    CONNECTING = "CONNECTING"
    AUTHENTICATED = "AUTHENTICATED"
    ACTIVE = "ACTIVE"
    DISCONNECTED = "DISCONNECTED"


_ALLOWED_TRANSITIONS: Final[dict[SessionState, frozenset[SessionState]]] = {
    SessionState.IDLE: frozenset({SessionState.CONNECTING}),
    SessionState.CONNECTING: frozenset(
        {SessionState.AUTHENTICATED, SessionState.DISCONNECTED}
    ),
    SessionState.AUTHENTICATED: frozenset({SessionState.ACTIVE, SessionState.DISCONNECTED}),
    SessionState.ACTIVE: frozenset({SessionState.DISCONNECTED}),
    SessionState.DISCONNECTED: frozenset(),
}


class InvalidStateTransitionError(Exception):
    def __init__(self, current: SessionState, target: SessionState) -> None:
        super().__init__(f"Cannot transition from {current.value} to {target.value}")
        self.current = current
        self.target = target


class RemoteDesktopSession:
    def __init__(self, session_id: str | None = None) -> None:
        self.session_id = session_id or str(uuid4())
        self._state = SessionState.IDLE
        self._permissions: frozenset[str] = frozenset()
        self._user_id: str | None = None
        self._controller_name: str | None = None
        self._started_at_ms: int | None = None

    @property
    def user_id(self) -> str | None:
        return self._user_id

    @property
    def controller_name(self) -> str | None:
        return self._controller_name

    @property
    def started_at_ms(self) -> int | None:
        return self._started_at_ms

    def bind_controller(
        self,
        user_id: str | None,
        controller_name: str | None = None,
    ) -> None:
        if user_id:
            self._user_id = user_id
        if controller_name:
            self._controller_name = controller_name

    def start_controller_session(self, started_at_ms: int) -> None:
        self._started_at_ms = started_at_ms


    @property
    def permissions(self) -> frozenset[str]:
        return self._permissions

    def set_permissions(self, permissions: frozenset[str]) -> None:
        self._permissions = permissions

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state == SessionState.DISCONNECTED

    @property
    def is_active(self) -> bool:
        return self._state in {
            SessionState.CONNECTING,
            SessionState.AUTHENTICATED,
            SessionState.ACTIVE,
        }

    def transition_to(self, target: SessionState) -> None:
        allowed = _ALLOWED_TRANSITIONS[self._state]
        if target not in allowed:
            raise InvalidStateTransitionError(self._state, target)

        previous = self._state
        self._state = target
        logger.info(
            "Session %s transitioned %s -> %s",
            self.session_id,
            previous.value,
            target.value,
        )

    def mark_connecting(self) -> None:
        self.transition_to(SessionState.CONNECTING)

    def mark_authenticated(self) -> None:
        self.transition_to(SessionState.AUTHENTICATED)

    def mark_active(self) -> None:
        self.transition_to(SessionState.ACTIVE)

    def mark_disconnected(self) -> None:
        if self._state != SessionState.DISCONNECTED:
            self.transition_to(SessionState.DISCONNECTED)

    def bind_remote_session_id(self, remote_session_id: str) -> None:
        if remote_session_id:
            self.session_id = remote_session_id
