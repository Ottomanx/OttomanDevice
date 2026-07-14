"""Avatar runtime plugin package for OttomanDevice."""

from ottomandevice.plugins.avatar.animation import AnimationController, AnimationRequest
from ottomandevice.plugins.avatar.emotion import Emotion, EmotionEngine
from ottomandevice.plugins.avatar.lipsync import LipSyncEngine, LipSyncFrame
from ottomandevice.plugins.avatar.manager import AvatarManager
from ottomandevice.plugins.avatar.plugin import OttomanAvatarPlugin
from ottomandevice.plugins.avatar.renderer import AvatarRenderFrame, AvatarRenderer, HeadlessAvatarRenderer
from ottomandevice.plugins.avatar.state import AvatarState, AvatarStateMachine

plugin_class = OttomanAvatarPlugin

__all__ = [
    "AnimationController",
    "AnimationRequest",
    "AvatarManager",
    "AvatarRenderFrame",
    "AvatarRenderer",
    "AvatarState",
    "AvatarStateMachine",
    "Emotion",
    "EmotionEngine",
    "HeadlessAvatarRenderer",
    "LipSyncEngine",
    "LipSyncFrame",
    "OttomanAvatarPlugin",
    "plugin_class",
]
