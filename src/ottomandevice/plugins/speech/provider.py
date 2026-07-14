from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TranscriptChunk:
    """Incremental speech-to-text result."""

    text: str
    is_final: bool = False
    confidence: float = 1.0
    language: str = "auto"


@dataclass(frozen=True)
class TranscriptionResult:
    """Final speech-to-text result."""

    text: str
    language: str
    confidence: float
    latency_ms: float
    provider: str


@dataclass(frozen=True)
class SynthesisChunk:
    """Incremental text-to-speech audio chunk."""

    audio: bytes
    done: bool = False


@dataclass(frozen=True)
class SynthesisResult:
    """Completed text-to-speech result."""

    audio: bytes
    latency_ms: float
    provider: str


@dataclass
class SpeechMetrics:
    """Latency and throughput metrics for speech providers."""

    stt_requests: int = 0
    tts_requests: int = 0
    stt_failures: int = 0
    tts_failures: int = 0
    stt_latency_ms: float = 0.0
    tts_latency_ms: float = 0.0

    @property
    def average_stt_latency_ms(self) -> float:
        return self.stt_latency_ms / self.stt_requests if self.stt_requests else 0.0

    @property
    def average_tts_latency_ms(self) -> float:
        return self.tts_latency_ms / self.tts_requests if self.tts_requests else 0.0


class STTProvider(ABC):
    """Abstract streaming speech-to-text provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return provider identifier."""

    @abstractmethod
    async def connect(self) -> None:
        """Validate credentials and prepare the provider."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Release provider resources."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Return whether the provider can accept requests."""

    @abstractmethod
    async def transcribe(self, pcm: bytes, *, language: str = "auto") -> TranscriptionResult:
        """Transcribe a PCM audio buffer."""

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        language: str = "auto",
    ) -> AsyncIterator[TranscriptChunk]:
        """Transcribe audio incrementally."""
        if False:
            yield TranscriptChunk(text="")


class TTSProvider(ABC):
    """Abstract streaming text-to-speech provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return provider identifier."""

    @abstractmethod
    async def connect(self) -> None:
        """Validate credentials and prepare the provider."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Release provider resources."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Return whether the provider can accept requests."""

    @abstractmethod
    async def synthesize(self, text: str, *, language: str = "auto") -> SynthesisResult:
        """Synthesize speech for the full text."""

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        *,
        language: str = "auto",
    ) -> AsyncIterator[SynthesisChunk]:
        """Synthesize speech incrementally."""
        if False:
            yield SynthesisChunk(audio=b"")
