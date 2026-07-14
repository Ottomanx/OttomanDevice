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
class CameraDetected(Event):
    """Published when a camera device is discovered."""

    device_id: int = 0
    width: int = 0
    height: int = 0
    backend: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_id": self.device_id,
                "width": self.width,
                "height": self.height,
                "backend": self.backend,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "width": self.width,
            "height": self.height,
            "backend": self.backend,
        }
        return data


@dataclass(frozen=True)
class CameraOpened(Event):
    """Published when the camera pipeline is opened."""

    device_id: int = 0
    backend: str = ""
    width: int = 0
    height: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_id": self.device_id,
                "backend": self.backend,
                "width": self.width,
                "height": self.height,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "backend": self.backend,
            "width": self.width,
            "height": self.height,
        }
        return data


@dataclass(frozen=True)
class CameraClosed(Event):
    """Published when the camera pipeline is closed."""

    device_id: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"device_id": self.device_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "device_id": self.device_id}
        return data


@dataclass(frozen=True)
class CameraFrameCaptured(Event):
    """Published when a camera frame is captured."""

    device_id: int = 0
    frame_number: int = 0
    width: int = 0
    height: int = 0
    streaming: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_id": self.device_id,
                "frame_number": self.frame_number,
                "width": self.width,
                "height": self.height,
                "streaming": self.streaming,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "frame_number": self.frame_number,
            "width": self.width,
            "height": self.height,
            "streaming": self.streaming,
        }
        return data


@dataclass(frozen=True)
class CameraDisconnected(Event):
    """Published when the active camera disconnects."""

    device_id: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"device_id": self.device_id, "reason": self.reason},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "reason": self.reason,
        }
        return data


@dataclass(frozen=True)
class CameraReconnected(Event):
    """Published when a disconnected camera reconnects."""

    device_id: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"device_id": self.device_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "device_id": self.device_id}
        return data


@dataclass(frozen=True)
class CameraError(Event):
    """Published when a camera operation fails."""

    device_id: int = 0
    operation: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_id": self.device_id,
                "operation": self.operation,
                "error": self.error,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "operation": self.operation,
            "error": self.error,
        }
        return data


@dataclass(frozen=True)
class AudioDetected(Event):
    """Published when a microphone is discovered."""

    device_id: int = 0
    name: str = ""
    sample_rate: int = 0
    channels: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_id": self.device_id,
                "name": self.name,
                "sample_rate": self.sample_rate,
                "channels": self.channels,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "name": self.name,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }
        return data


@dataclass(frozen=True)
class AudioStarted(Event):
    """Published when audio capture starts."""

    device_id: int = 0
    sample_rate: int = 0
    channels: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_id": self.device_id,
                "sample_rate": self.sample_rate,
                "channels": self.channels,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
        }
        return data


@dataclass(frozen=True)
class AudioStopped(Event):
    """Published when audio capture stops."""

    device_id: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"device_id": self.device_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "device_id": self.device_id}
        return data


@dataclass(frozen=True)
class AudioFrameCaptured(Event):
    """Published when a PCM chunk is captured."""

    device_id: int = 0
    chunk_number: int = 0
    sample_rate: int = 0
    channels: int = 0
    bytes_length: int = 0
    input_level_db: float = -100.0
    streaming: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_id": self.device_id,
                "chunk_number": self.chunk_number,
                "sample_rate": self.sample_rate,
                "channels": self.channels,
                "bytes_length": self.bytes_length,
                "input_level_db": self.input_level_db,
                "streaming": self.streaming,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "chunk_number": self.chunk_number,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "bytes_length": self.bytes_length,
            "input_level_db": self.input_level_db,
            "streaming": self.streaming,
        }
        return data


@dataclass(frozen=True)
class AudioDisconnected(Event):
    """Published when the active microphone disconnects."""

    device_id: int = 0
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"device_id": self.device_id, "reason": self.reason},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "reason": self.reason,
        }
        return data


@dataclass(frozen=True)
class AudioReconnected(Event):
    """Published when a disconnected microphone reconnects."""

    device_id: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"device_id": self.device_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "device_id": self.device_id}
        return data


@dataclass(frozen=True)
class AudioSilenceDetected(Event):
    """Published when captured audio falls below the silence threshold."""

    device_id: int = 0
    input_level_db: float = -100.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_id": self.device_id,
                "input_level_db": self.input_level_db,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "input_level_db": self.input_level_db,
        }
        return data


@dataclass(frozen=True)
class AudioError(Event):
    """Published when an audio operation fails."""

    device_id: int = 0
    operation: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_id": self.device_id,
                "operation": self.operation,
                "error": self.error,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_id": self.device_id,
            "operation": self.operation,
            "error": self.error,
        }
        return data


@dataclass(frozen=True)
class AIProviderConnected(Event):
    """Published when an AI provider connects successfully."""

    provider: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"provider": self.provider, "model": self.model},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "provider": self.provider, "model": self.model}
        return data


@dataclass(frozen=True)
class AIProviderDisconnected(Event):
    """Published when an AI provider disconnects or becomes unavailable."""

    provider: str = ""
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"provider": self.provider, "reason": self.reason},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "provider": self.provider, "reason": self.reason}
        return data


@dataclass(frozen=True)
class AIRequestStarted(Event):
    """Published when an AI inference request begins."""

    request_id: str = ""
    session_id: str = ""
    provider: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "request_id": self.request_id,
                "session_id": self.session_id,
                "provider": self.provider,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "request_id": self.request_id,
            "session_id": self.session_id,
            "provider": self.provider,
        }
        return data


@dataclass(frozen=True)
class AIRequestCompleted(Event):
    """Published when an AI inference request completes."""

    request_id: str = ""
    session_id: str = ""
    provider: str = ""
    duration_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "request_id": self.request_id,
                "session_id": self.session_id,
                "provider": self.provider,
                "duration_ms": self.duration_ms,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "request_id": self.request_id,
            "session_id": self.session_id,
            "provider": self.provider,
            "duration_ms": self.duration_ms,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }
        return data


@dataclass(frozen=True)
class AIRequestFailed(Event):
    """Published when an AI inference request fails."""

    request_id: str = ""
    session_id: str = ""
    provider: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "request_id": self.request_id,
                "session_id": self.session_id,
                "provider": self.provider,
                "error": self.error,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "request_id": self.request_id,
            "session_id": self.session_id,
            "provider": self.provider,
            "error": self.error,
        }
        return data


@dataclass(frozen=True)
class AIResponseStreamStarted(Event):
    """Published when a streaming AI response begins."""

    request_id: str = ""
    session_id: str = ""
    provider: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "request_id": self.request_id,
                "session_id": self.session_id,
                "provider": self.provider,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "request_id": self.request_id,
            "session_id": self.session_id,
            "provider": self.provider,
        }
        return data


@dataclass(frozen=True)
class AIResponseStreamCompleted(Event):
    """Published when a streaming AI response completes."""

    request_id: str = ""
    session_id: str = ""
    provider: str = ""
    duration_ms: float = 0.0
    total_tokens: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "request_id": self.request_id,
                "session_id": self.session_id,
                "provider": self.provider,
                "duration_ms": self.duration_ms,
                "total_tokens": self.total_tokens,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "request_id": self.request_id,
            "session_id": self.session_id,
            "provider": self.provider,
            "duration_ms": self.duration_ms,
            "total_tokens": self.total_tokens,
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
class PluginInstalled(Event):
    """Published when a plugin completes installation."""

    plugin_id: str = ""
    name: str = ""
    version: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"plugin_id": self.plugin_id, "name": self.name, "version": self.version},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id, "name": self.name, "version": self.version}
        return data


@dataclass(frozen=True)
class PluginInitialized(Event):
    """Published when a plugin completes initialization."""

    plugin_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"plugin_id": self.plugin_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id}
        return data


@dataclass(frozen=True)
class PluginStarted(Event):
    """Published when a plugin starts successfully."""

    plugin_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"plugin_id": self.plugin_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id}
        return data


@dataclass(frozen=True)
class PluginStopped(Event):
    """Published when a plugin stops successfully."""

    plugin_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"plugin_id": self.plugin_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id}
        return data


@dataclass(frozen=True)
class PluginUninstalled(Event):
    """Published when a plugin is uninstalled."""

    plugin_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", {"plugin_id": self.plugin_id})

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id}
        return data


@dataclass(frozen=True)
class PluginFailed(Event):
    """Published when a plugin lifecycle operation fails."""

    plugin_id: str = ""
    phase: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"plugin_id": self.plugin_id, "phase": self.phase, "error": self.error},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "plugin_id": self.plugin_id, "phase": self.phase, "error": self.error}
        return data




@dataclass(frozen=True)
class DeviceRegistered(Event):
    """Published when a device registers successfully with the cloud backend."""

    device_uuid: str = ""
    installation_id: str = ""
    is_new: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_uuid": self.device_uuid,
                "installation_id": self.installation_id,
                "is_new": self.is_new,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_uuid": self.device_uuid,
            "installation_id": self.installation_id,
            "is_new": self.is_new,
        }
        return data


@dataclass(frozen=True)
class DeviceRegistrationFailed(Event):
    """Published when cloud device registration fails."""

    device_uuid: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"device_uuid": self.device_uuid, "error": self.error},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {**data["payload"], "device_uuid": self.device_uuid, "error": self.error}
        return data


@dataclass(frozen=True)
class DeviceProfileUpdated(Event):
    """Published when the runtime device profile is synchronized to the cloud."""

    device_uuid: str = ""
    plugin_count: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {"device_uuid": self.device_uuid, "plugin_count": self.plugin_count},
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_uuid": self.device_uuid,
            "plugin_count": self.plugin_count,
        }
        return data




@dataclass(frozen=True)
class HeartbeatReceived(Event):
    """Published when a heartbeat is successfully acknowledged by the cloud."""

    device_uuid: str = ""
    uptime: int = 0
    cpu: float = 0.0
    ram: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "device_uuid": self.device_uuid,
                "uptime": self.uptime,
                "cpu": self.cpu,
                "ram": self.ram,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "device_uuid": self.device_uuid,
            "uptime": self.uptime,
            "cpu": self.cpu,
            "ram": self.ram,
        }
        return data


@dataclass(frozen=True)
class RemoteCommandReceived(Event):
    """Published when a remote command is received from the cloud."""

    command_id: str = ""
    command: str = ""
    device_uuid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "command_id": self.command_id,
                "command": self.command,
                "device_uuid": self.device_uuid,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "command_id": self.command_id,
            "command": self.command,
            "device_uuid": self.device_uuid,
        }
        return data


@dataclass(frozen=True)
class RemoteCommandExecuted(Event):
    """Published when a remote command completes successfully."""

    command_id: str = ""
    command: str = ""
    device_uuid: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "command_id": self.command_id,
                "command": self.command,
                "device_uuid": self.device_uuid,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "command_id": self.command_id,
            "command": self.command,
            "device_uuid": self.device_uuid,
        }
        return data


@dataclass(frozen=True)
class RemoteCommandFailed(Event):
    """Published when a remote command fails to execute."""

    command_id: str = ""
    command: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            {
                "command_id": self.command_id,
                "command": self.command,
                "error": self.error,
            },
        )

    def to_dict(self) -> dict[str, Any]:
        data = super().to_dict()
        data["payload"] = {
            **data["payload"],
            "command_id": self.command_id,
            "command": self.command,
            "error": self.error,
        }
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
