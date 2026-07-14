"""Audio plugin package for OttomanDevice."""

from ottomandevice.plugins.audio.capture import AudioCapture, ChunkResult
from ottomandevice.plugins.audio.device import MicrophoneDevice
from ottomandevice.plugins.audio.health import AudioHealth, AudioHealthSnapshot
from ottomandevice.plugins.audio.manager import AudioManager
from ottomandevice.plugins.audio.plugin import OttomanAudioPlugin

plugin_class = OttomanAudioPlugin

__all__ = [
    "AudioCapture",
    "AudioHealth",
    "AudioHealthSnapshot",
    "AudioManager",
    "ChunkResult",
    "MicrophoneDevice",
    "OttomanAudioPlugin",
    "plugin_class",
]
