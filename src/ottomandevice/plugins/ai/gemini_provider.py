from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator

import httpx

from ottomandevice.plugins.ai.provider import AIMessage, AIProvider, AIResponse, AIStreamChunk


class GeminiProvider(AIProvider):
    """Google Gemini generateContent provider."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        self._model = model
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

    async def connect(self) -> None:
        if not self._api_key:
            raise ConnectionError("GEMINI_API_KEY is not configured")
        self._client = httpx.AsyncClient(timeout=self._timeout)
        url = self._model_url(stream=False)
        response = await self._client.post(
            url,
            params={"key": self._api_key},
            json={"contents": [{"role": "user", "parts": [{"text": "ping"}]}]},
        )
        response.raise_for_status()
        self._connected = True

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._connected = False

    async def is_available(self) -> bool:
        return self._connected and self._client is not None and bool(self._api_key)

    async def complete(
        self,
        messages: tuple[AIMessage, ...],
        *,
        model: str | None = None,
    ) -> AIResponse:
        client = self._require_client()
        started = time.perf_counter()
        if model and model != self._model:
            self._model = model
        payload = {"contents": self._to_gemini_contents(messages)}
        response = await client.post(self._model_url(stream=False), params={"key": self._api_key}, json=payload)
        response.raise_for_status()
        body = response.json()
        text = body["candidates"][0]["content"]["parts"][0]["text"]
        usage = body.get("usageMetadata", {})
        latency_ms = (time.perf_counter() - started) * 1000
        prompt_tokens = int(usage.get("promptTokenCount", 0))
        completion_tokens = int(usage.get("candidatesTokenCount", 0))
        return AIResponse(
            text=str(text),
            provider=self.name,
            model=self._model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        messages: tuple[AIMessage, ...],
        *,
        model: str | None = None,
    ) -> AsyncIterator[AIStreamChunk]:
        client = self._require_client()
        if model and model != self._model:
            self._model = model
        payload = {"contents": self._to_gemini_contents(messages)}
        async with client.stream(
            "POST",
            self._model_url(stream=True),
            params={"key": self._api_key},
            json=payload,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                body = json.loads(line)
                parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                for part in parts:
                    text = part.get("text")
                    if text:
                        yield AIStreamChunk(text=text, done=False, provider=self.name)
            yield AIStreamChunk(text="", done=True, provider=self.name)

    def _model_url(self, *, stream: bool) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        return f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:{action}"

    @staticmethod
    def _to_gemini_contents(messages: tuple[AIMessage, ...]) -> list[dict[str, object]]:
        contents: list[dict[str, object]] = []
        for message in messages:
            role = "user" if message.role == "user" else "model"
            if message.role == "system":
                role = "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})
        return contents

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Gemini provider is not connected")
        return self._client
