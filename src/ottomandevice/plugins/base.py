from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class PluginMetadata:
    """Immutable metadata describing a runtime plugin."""

    id: str
    name: str
    version: str
    author: str
    dependencies: tuple[str, ...] = ()
    description: str = ""


class PluginState(str, Enum):
    """Lifecycle states for managed plugins."""

    DISCOVERED = "discovered"
    INSTALLED = "installed"
    INITIALIZED = "initialized"
    STARTED = "started"
    STOPPED = "stopped"
    UNINSTALLED = "uninstalled"
    FAILED = "failed"


class BasePlugin(ABC):
    """Abstract base class for all OttomanDevice plugins."""

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""

    @abstractmethod
    def install(self) -> None:
        """Prepare plugin resources on the host."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize plugin runtime state."""

    @abstractmethod
    def start(self) -> None:
        """Start plugin execution."""

    @abstractmethod
    def stop(self) -> None:
        """Stop plugin execution."""

    @abstractmethod
    def uninstall(self) -> None:
        """Remove plugin resources from the host."""


class DevicePlugin(BasePlugin):
    """Base class for device capability plugins."""


class AIPlugin(BasePlugin):
    """Base class for AI inference plugins."""


class CameraPlugin(BasePlugin):
    """Base class for camera pipeline plugins."""


class AudioPlugin(BasePlugin):
    """Base class for audio pipeline plugins."""


class SpeechPlugin(BasePlugin):
    """Base class for speech runtime plugins."""


class AvatarPlugin(BasePlugin):
    """Base class for avatar runtime plugins."""
