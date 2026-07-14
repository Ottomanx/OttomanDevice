from __future__ import annotations

import io
import os
import time
from collections.abc import AsyncIterator

import httpx

from ottomandevice.plugins.speech.provider import (
    STTProvider,
    TranscriptChunk,
    TranscriptionResult,
)


class WhisperProvider(STTProvider):
    """OpenAI Whisper speech-to-text provider."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "whisper-1",
        base_url: str = "https://api.openai.com/v1",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    @property
    def name(self) -> str:
        return "whisper"

    async def connect(self) -> None:
        if not self._api_key:
            raise ConnectionError("OPENAI_API_KEY is not configured")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=self._timeout,
        )
        response = await self._client.get("/models")
        response.raise_for_status()
        self._connected = True

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._connected = False

    async def is_available(self) -> bool:
        return self._connected and self._client is not None

    async def transcribe(self, pcm: bytes, *, language: str = "auto") -> TranscriptionResult:
        client = self._require_client()
        started = time.perf_counter()
        files = {"file": ("audio.wav", self._pcm_to_wav(pcm), "audio/wav")}
        data = {"model": self._model}
        if language != "auto":
            data["language"] = language
        response = await client.post("/audio/transcriptions", data=data, files=files)
        response.raise_for_status()
        body = response.json()
        latency_ms = (time.perf_counter() - started) * 1000
        return TranscriptionResult(
            text=str(body.get("text", "")),
            language=language,
            confidence=1.0,
            latency_ms=latency_ms,
            provider=self.name,
        )

    async def transcribe_stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        language: str = "auto",
    ) -> AsyncIterator[TranscriptChunk]:
        buffer = bytearray()
        async for chunk in audio_chunks:
            if not chunk:
                continue
            buffer.extend(chunk)
            yield TranscriptChunk(text="", is_final=False, confidence=0.0, language=language)
        if buffer:
            result = await self.transcribe(bytes(buffer), language=language)
            yield TranscriptChunk(
                text=result.text,
                is_final=True,
                confidence=result.confidence,
                language=result.language,
            )

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Whisper provider is not connected")
        return self._client

    @staticmethod
    def _pcm_to_wav(pcm: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
        import struct

        byte_rate = sample_rate * channels * 2
        block_align = channels * 2
        data_size = len(pcm)
        header = struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + data_size,
            b"WAVE",
            b"fmt ",
            16,
            1,
            channels,
            sample_rate,
            byte_rate,
            block_align,
            16,
            b"data",
            data_size,
        )
        return header + pcm
