from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator

import httpx

from ottomandevice.plugins.ai.provider import AIMessage, AIProvider, AIResponse, AIStreamChunk


class OllamaProvider(AIProvider):
    """Local Ollama chat provider."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str = "llama3.2",
        timeout: float = 120.0,
    ) -> None:
        self._base_url = (base_url or os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._connected = False

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def model(self) -> str:
        return self._model

    async def connect(self) -> None:
        self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        response = await self._client.get("/api/tags")
        response.raise_for_status()
        self._connected = True

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
        self._client = None
        self._connected = False

    async def is_available(self) -> bool:
        return self._connected and self._client is not None

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
        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
        body = response.json()
        text = body["message"]["content"]
        prompt_tokens = int(body.get("prompt_eval_count", 0))
        completion_tokens = int(body.get("eval_count", 0))
        latency_ms = (time.perf_counter() - started) * 1000
        return AIResponse(
            text=str(text),
            provider=self.name,
            model=payload["model"],
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
        payload = {
            "model": model or self._model,
            "messages": [{"role": item.role, "content": item.content} for item in messages],
            "stream": True,
        }
        async with client.stream("POST", "/api/chat", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                body = json.loads(line)
                chunk = body.get("message", {}).get("content") or ""
                done = bool(body.get("done"))
                if chunk:
                    yield AIStreamChunk(text=chunk, done=False, provider=self.name)
                if done:
                    yield AIStreamChunk(text="", done=True, provider=self.name)
                    return

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Ollama provider is not connected")
        return self._client
