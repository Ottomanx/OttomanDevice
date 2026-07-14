from __future__ import annotations

import os
import time
import uuid
from collections.abc import AsyncIterator

import httpx

from ottomandevice.plugins.speech.provider import (
    STTProvider,
    SynthesisChunk,
    SynthesisResult,
    TranscriptChunk,
    TranscriptionResult,
    TTSProvider,
)


class AzureSpeechProvider(STTProvider, TTSProvider):
    """Microsoft Azure Cognitive Services speech provider."""

    def __init__(
        self,
        *,
        subscription_key: str | None = None,
        region: str | None = None,
        voice: str = "en-US-JennyNeural",
        timeout: float = 60.0,
    ) -> None:
        self._subscription_key = subscription_key or os.getenv("AZURE_SPEECH_KEY", "").strip()
        self._region = region or os.getenv("AZURE_SPEECH_REGION", "eastus").strip()
        self._voice = voice
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    @property
    def name(self) -> str:
        return "azure"

    async def connect(self) -> None:
        if not self._subscription_key:
            raise ConnectionError("AZURE_SPEECH_KEY is not configured")
        self._client = httpx.AsyncClient(timeout=self._timeout)
        token = await self._fetch_token()
        if not token:
            raise ConnectionError("Unable to fetch Azure speech token")
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
        token = await self._fetch_token()
        locale = "en-US" if language == "auto" else language
        url = f"https://{self._region}.stt.speech.microsoft.com/speech/recognition/conversation/cognitiveservices/v1"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "audio/wav; codecs=audio/pcm; samplerate=16000",
            "Accept": "application/json",
        }
        response = await client.post(url, params={"language": locale}, headers=headers, content=pcm)
        response.raise_for_status()
        body = response.json()
        text = str(body.get("DisplayText") or body.get("Text") or "")
        latency_ms = (time.perf_counter() - started) * 1000
        return TranscriptionResult(
            text=text,
            language=locale,
            confidence=float(body.get("Confidence", 1.0) or 1.0),
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
            buffer.extend(chunk)
            yield TranscriptChunk(text="", is_final=False, language=language)
        if buffer:
            result = await self.transcribe(bytes(buffer), language=language)
            yield TranscriptChunk(text=result.text, is_final=True, confidence=result.confidence, language=result.language)

    async def synthesize(self, text: str, *, language: str = "auto") -> SynthesisResult:
        client = self._require_client()
        started = time.perf_counter()
        token = await self._fetch_token()
        url = f"https://{self._region}.tts.speech.microsoft.com/cognitiveservices/v1"
        ssml = (
            "<speak version='1.0' xml:lang='en-US'>"
            f"<voice name='{self._voice}'>{text}</voice></speak>"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
        }
        response = await client.post(url, headers=headers, content=ssml.encode("utf-8"))
        response.raise_for_status()
        latency_ms = (time.perf_counter() - started) * 1000
        return SynthesisResult(audio=response.content, latency_ms=latency_ms, provider=self.name)

    async def synthesize_stream(
        self,
        text: str,
        *,
        language: str = "auto",
    ) -> AsyncIterator[SynthesisChunk]:
        result = await self.synthesize(text, language=language)
        chunk_size = 4096
        audio = result.audio
        for index in range(0, len(audio), chunk_size):
            yield SynthesisChunk(audio=audio[index : index + chunk_size], done=False)
        yield SynthesisChunk(audio=b"", done=True)

    async def _fetch_token(self) -> str:
        client = self._require_client()
        url = f"https://{self._region}.api.cognitive.microsoft.com/sts/v1.0/issueToken"
        headers = {"Ocp-Apim-Subscription-Key": self._subscription_key}
        response = await client.post(url, headers=headers)
        response.raise_for_status()
        return response.text

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Azure speech provider is not connected")
        return self._client
