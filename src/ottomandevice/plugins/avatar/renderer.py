from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from ottomandevice.plugins.avatar.state import AvatarState


@dataclass(frozen=True)
class AvatarRenderFrame:
    """Frame payload sent to a renderer backend."""

    state: AvatarState
    emotion: str
    animation: str | None
    mouth_openness: float
    viseme: str
    blend_shapes: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class AvatarRenderer(ABC):
    """Abstract renderer for Unity, Unreal, WebGL, or headless backends."""

    @property
    @abstractmethod
    def backend(self) -> str:
        """Return renderer backend identifier."""

    @abstractmethod
    async def initialize(self, *, target_fps: int = 60) -> None:
        """Prepare renderer resources."""

    @abstractmethod
    async def load_avatar(self, asset_id: str = "default") -> None:
        """Load avatar assets into the renderer."""

    @abstractmethod
    async def render(self, frame: AvatarRenderFrame) -> None:
        """Render a single avatar frame."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Release renderer resources."""


class HeadlessAvatarRenderer(AvatarRenderer):
    """Cross-platform renderer that records frames without GPU output."""

    def __init__(self) -> None:
        self._initialized = False
        self._loaded = False
        self.frames: list[AvatarRenderFrame] = []

    @property
    def backend(self) -> str:
        return "headless"

    async def initialize(self, *, target_fps: int = 60) -> None:
        self._initialized = True

    async def load_avatar(self, asset_id: str = "default") -> None:
        if not self._initialized:
            raise RuntimeError("Renderer is not initialized")
        self._loaded = True

    async def render(self, frame: AvatarRenderFrame) -> None:
        if not self._loaded:
            raise RuntimeError("Avatar is not loaded")
        self.frames.append(frame)

    async def shutdown(self) -> None:
        self._initialized = False
        self._loaded = False
