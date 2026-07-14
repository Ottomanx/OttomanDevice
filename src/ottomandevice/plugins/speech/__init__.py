"""Speech runtime plugin package for OttomanDevice."""

from ottomandevice.plugins.speech.azure_provider import AzureSpeechProvider
from ottomandevice.plugins.speech.buffer import AudioBuffer
from ottomandevice.plugins.speech.elevenlabs_provider import ElevenLabsProvider
from ottomandevice.plugins.speech.manager import SpeechManager
from ottomandevice.plugins.speech.pipeline import SpeechPipeline
from ottomandevice.plugins.speech.plugin import OttomanSpeechPlugin
from ottomandevice.plugins.speech.provider import (
    STTProvider,
    SynthesisChunk,
    SynthesisResult,
    TranscriptChunk,
    TranscriptionResult,
    TTSProvider,
)
from ottomandevice.plugins.speech.vad import VoiceActivityDetector
from ottomandevice.plugins.speech.whisper_provider import WhisperProvider
from ottomandevice.plugins.speech.wake_word import WakeWordFramework

plugin_class = OttomanSpeechPlugin

__all__ = [
    "AudioBuffer",
    "AzureSpeechProvider",
    "ElevenLabsProvider",
    "OttomanSpeechPlugin",
    "SpeechManager",
    "SpeechPipeline",
    "STTProvider",
    "SynthesisChunk",
    "SynthesisResult",
    "TranscriptChunk",
    "TranscriptionResult",
    "TTSProvider",
    "VoiceActivityDetector",
    "WakeWordFramework",
    "WhisperProvider",
    "plugin_class",
]
