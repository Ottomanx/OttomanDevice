from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from ottomandevice.plugins.ai.provider import AIMessage, AIProvider, AIResponse, AIStreamChunk


class OpenAIProvider(AIProvider):
    """OpenAI chat completions provider."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
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
        return "openai"

    @property
    def model(self) -> str:
        return self._model

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
        return self._connected and self._client is not None and bool(self._api_key)

    async def complete(
        self,
        messages: tuple[AIMessage, ...],
        *,
        model: str | None = None,
    ) -> AIResponse:
        client = self._require_client()
        started = time.perf_counter()
        payload = {
            "model": model or self._model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "stream": False,
        }
        response = await client.post("/chat/completions", json=payload)
        response.raise_for_status()
        body = response.json()
        choice = body["choices"][0]["message"]["content"]
        usage = body.get("usage", {})
        latency_ms = (time.perf_counter() - started) * 1000
        return AIResponse(
            text=str(choice),
            provider=self.name,
            model=payload["model"],
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
            latency_ms=latency_ms,
        )

    async def stream(
        self,
        messages: tuple[AIMessage, ...],
        *,
        model: str | None = None,
    ) -> AsyncIterator[AIStreamChunk]:
        client = self._require_client()
        payload = {
            "model": model or self._model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "stream": True,
        }
        async with client.stream("POST", "/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data = line.removeprefix("data: ").strip()
                if data == "[DONE]":
                    yield AIStreamChunk(text="", done=True, provider=self.name)
                    return
                chunk = json.loads(data)
                delta = chunk["choices"][0]["delta"].get("content") or ""
                if delta:
                    yield AIStreamChunk(text=delta, done=False, provider=self.name)

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("OpenAI provider is not connected")
        return self._client
