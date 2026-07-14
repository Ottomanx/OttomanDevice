from __future__ import annotations

import asyncio
import fnmatch
import inspect
import threading
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

DEFAULT_PRIORITY = 0
MAX_HISTORY = 1000
WILDCARD_ALL = "*"

EventHandler = Callable[["Event"], None]
AsyncEventHandler = Callable[["Event"], Awaitable[None]]
Handler = EventHandler | AsyncEventHandler


@dataclass(frozen=True)
class Event:
    """Base runtime event."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    priority: int = DEFAULT_PRIORITY
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def event_type(self) -> str:
        """Return the canonical event type name."""
        return type(self).__name__

    def to_dict(self) -> dict[str, Any]:
        """Serialize the event to a plain dictionary."""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "priority": self.priority,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True)
class RuntimeStarted(Event):
    """Published when the production runtime finishes booting."""


@dataclass(frozen=True)
class RuntimeStopping(Event):
    """Published when the production runtime begins shutdown."""


@dataclass(frozen=True)
class ServiceStarted(Event):
    """Published when a managed service starts successfully."""

    service_name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"service_name": self.service_name})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "service_name": self.service_name}
        return data


@dataclass(frozen=True)
class ServiceStopped(Event):
    """Published when a managed service stops successfully."""

    service_name: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"service_name": self.service_name})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "service_name": self.service_name}
        return data


@dataclass(frozen=True)
class ServiceFailed(Event):
    """Published when a managed service fails to start, stop, or run."""

    service_name: str = ""
    error: str = ""
    context: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "service_name": self.service_name,
                "error": self.error,
                "context": self.context,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "service_name": self.service_name,
            "error": self.error,
            "context": self.context,
        }
        return data


@dataclass(frozen=True)
class HealthUpdated(Event):
    """Published when host health metrics are collected."""

    status: str = "ok"
    metrics: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"status": self.status, "metrics": list(self.metrics)},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            "status": self.status,
            "metrics": list(self.metrics),
        }
        return data


@dataclass(frozen=True)
class HeartbeatSent(Event):
    """Published when a device heartbeat is sent to the cloud."""

    device_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"device_id": self.device_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "device_id": self.device_id}
        return data


@dataclass(frozen=True)
class CameraOpened(Event):
    """Published when the camera pipeline is opened."""

    backend: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"backend": self.backend})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "backend": self.backend}
        return data


@dataclass(frozen=True)
class CameraClosed(Event):
    """Published when the camera pipeline is closed."""


@dataclass(frozen=True)
class AudioStarted(Event):
    """Published when audio capture starts."""


@dataclass(frozen=True)
class AudioStopped(Event):
    """Published when audio capture stops."""


@dataclass(frozen=True)
class AIRequestStarted(Event):
    """Published when an AI inference request begins."""

    request_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"request_id": self.request_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "request_id": self.request_id}
        return data


@dataclass(frozen=True)
class AIRequestCompleted(Event):
    """Published when an AI inference request completes."""

    request_id: str = ""
    duration_ms: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"request_id": self.request_id, "duration_ms": self.duration_ms})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "request_id": self.request_id,
            "duration_ms": self.duration_ms,
        }
        return data


@dataclass(frozen=True)
class CloudConnected(Event):
    """Published when the cloud backend connection is established."""

    provider: str = "supabase"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "provider": self.provider}
        return data


@dataclass(frozen=True)
class CloudDisconnected(Event):
    """Published when the cloud backend connection is closed."""

    provider: str = "supabase"

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "provider": self.provider}
        return data


@dataclass(frozen=True)
class Subscription:
    """Registered event handler subscription."""

    subscription_id: str
    event_type: str
    handler: Handler
    priority: int
    is_async: bool


class EventBus:
    """Thread-safe runtime event bus with async dispatch support."""

    _instance: "EventBus | None" = None
    _instance_lock = threading.Lock()

    def __init__(self, *, max_history: int = MAX_HISTORY) -> None:
        self._max_history = max_history
        self._subscriptions: dict[str, Subscription] = {}
        self._history: deque[Event] = deque(maxlen=max_history)
        self._lock = threading.RLock()
        self._async_loop: asyncio.AbstractEventLoop | None = None
        self._async_thread: threading.Thread | None = None
        self._async_ready = threading.Event()

    @classmethod
    def get_instance(cls) -> "EventBus":
        """Return the process-wide event bus singleton."""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def history(self) -> tuple[Event, ...]:
        """Return a snapshot of recorded event history."""
        with self._lock:
            return tuple(self._history)

    def publish(self, event: Event) -> None:
        """Publish an event to matching subscribers."""
        with self._lock:
            self._history.append(event)
            subscriptions = self._matching_subscriptions(event)

        for subscription in subscriptions:
            self._dispatch(subscription, event)

    def subscribe(
        self,
        event_type: str | type[Event],
        handler: Handler | None = None,
        *,
        priority: int = DEFAULT_PRIORITY,
    ) -> Callable[[Handler], Handler] | str:
        """Subscribe to an event type or wildcard pattern."""
        pattern = self._normalize_event_type(event_type)

        def decorator(func: Handler) -> Handler:
            self._register(pattern, func, priority=priority)
            return func

        if handler is not None:
            return self._register(pattern, handler, priority=priority)
        return decorator

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription by identifier."""
        with self._lock:
            return self._subscriptions.pop(subscription_id, None) is not None

    def clear_history(self) -> None:
        """Clear stored event history."""
        with self._lock:
            self._history.clear()

    def shutdown(self) -> None:
        """Stop the async dispatcher thread."""
        loop = self._async_loop
        if loop is None:
            return

        loop.call_soon_threadsafe(loop.stop)
        if self._async_thread and self._async_thread.is_alive():
            self._async_thread.join(timeout=2)
        self._async_loop = None
        self._async_thread = None
        self._async_ready.clear()

    def _register(self, event_type: str, handler: Handler, *, priority: int) -> str:
        subscription_id = str(uuid.uuid4())
        subscription = Subscription(
            subscription_id=subscription_id,
            event_type=event_type,
            handler=handler,
            priority=priority,
            is_async=inspect.iscoroutinefunction(handler),
        )
        with self._lock:
            self._subscriptions[subscription_id] = subscription
        return subscription_id

    def _matching_subscriptions(self, event: Event) -> list[Subscription]:
        matches = [
            subscription
            for subscription in self._subscriptions.values()
            if self._matches(subscription.event_type, event.event_type)
        ]
        return sorted(
            matches,
            key=lambda item: (item.priority, event.priority),
            reverse=True,
        )

    def _matches(self, pattern: str, event_type: str) -> bool:
        if pattern == WILDCARD_ALL:
            return True
        return fnmatch.fnmatchcase(event_type, pattern)

    def _dispatch(self, subscription: Subscription, event: Event) -> None:
        if subscription.is_async:
            self._dispatch_async(subscription.handler, event)
            return

        try:
            subscription.handler(event)
        except Exception:
            return

    def _dispatch_async(self, handler: AsyncEventHandler, event: Event) -> None:
        loop = self._ensure_async_loop()

        async def _run() -> None:
            try:
                await handler(event)
            except Exception:
                return

        asyncio.run_coroutine_threadsafe(_run(), loop)

    def _ensure_async_loop(self) -> asyncio.AbstractEventLoop:
        if self._async_loop is not None:
            self._async_ready.wait(timeout=2)
            assert self._async_loop is not None
            return self._async_loop

        with self._lock:
            if self._async_loop is not None:
                self._async_ready.wait(timeout=2)
                assert self._async_loop is not None
                return self._async_loop

            ready = threading.Event()

            def _runner() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._async_loop = loop
                self._async_ready.set()
                ready.set()
                loop.run_forever()
                loop.close()

            self._async_thread = threading.Thread(
                target=_runner,
                name="event-bus-async",
                daemon=True,
            )
            self._async_thread.start()
            ready.wait(timeout=2)

        assert self._async_loop is not None
        return self._async_loop

    @staticmethod
    def _normalize_event_type(event_type: str | type[Event]) -> str:
        if isinstance(event_type, str):
            return event_type
        return event_type.__name__
