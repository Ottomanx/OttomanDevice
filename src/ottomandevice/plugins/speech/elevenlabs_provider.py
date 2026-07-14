from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator

import httpx

from ottomandevice.plugins.speech.provider import SynthesisChunk, SynthesisResult, TTSProvider


class ElevenLabsProvider(TTSProvider):
    """ElevenLabs streaming text-to-speech provider."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        voice_id: str | None = None,
        model_id: str = "eleven_multilingual_v2",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.getenv("ELEVENLABS_API_KEY", "").strip()
        self._voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        self._model_id = model_id
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    @property
    def name(self) -> str:
        return "elevenlabs"

    async def connect(self) -> None:
        if not self._api_key:
            raise ConnectionError("ELEVENLABS_API_KEY is not configured")
        self._client = httpx.AsyncClient(
            base_url="https://api.elevenlabs.io/v1",
            headers={"xi-api-key": self._api_key},
            timeout=self._timeout,
        )
        response = await self._client.get("/user")
        response.raise_for_status()
        self._connected = True

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._connected = False

    async def is_available(self) -> bool:
        return self._connected and self._client is not None

    async def synthesize(self, text: str, *, language: str = "auto") -> SynthesisResult:
        client = self._require_client()
        started = time.perf_counter()
        payload = {"text": text, "model_id": self._model_id}
        response = await client.post(f"/text-to-speech/{self._voice_id}", json=payload)
        response.raise_for_status()
        latency_ms = (time.perf_counter() - started) * 1000
        return SynthesisResult(audio=response.content, latency_ms=latency_ms, provider=self.name)

    async def synthesize_stream(
        self,
        text: str,
        *,
        language: str = "auto",
    ) -> AsyncIterator[SynthesisChunk]:
        client = self._require_client()
        payload = {"text": text, "model_id": self._model_id}
        async with client.stream("POST", f"/text-to-speech/{self._voice_id}/stream", json=payload) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                if chunk:
                    yield SynthesisChunk(audio=chunk, done=False)
        yield SynthesisChunk(audio=b"", done=True)

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("ElevenLabs provider is not connected")
        return self._client
