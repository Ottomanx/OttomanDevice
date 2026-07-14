from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ottomandevice.config import settings
from ottomandevice.core.event_bus import (
    AIProviderConnected,
    AIProviderDisconnected,
    AIRequestCompleted,
    AIRequestFailed,
    AIRequestStarted,
    AIResponseStreamCompleted,
    AIResponseStreamStarted,
    EventBus,
)
from ottomandevice.plugins.ai.conversation import AIConversation
from ottomandevice.plugins.ai.gemini_provider import GeminiProvider
from ottomandevice.plugins.ai.ollama_provider import OllamaProvider
from ottomandevice.plugins.ai.openai_provider import OpenAIProvider
from ottomandevice.plugins.ai.prompts import PromptManager
from ottomandevice.plugins.ai.provider import AIProvider, AIResponse, AIStreamChunk, ProviderMetrics


@dataclass
class AIRequestRecord:
    """Tracked request metadata."""

    request_id: str
    session_id: str
    provider: str
    started_at: float = field(default_factory=time.perf_counter)


class AIManager:
    """Orchestrates AI providers, sessions, failover, and multimodal context."""

    _instance: AIManager | None = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        providers: dict[str, AIProvider] | None = None,
    ) -> None:
        self._event_bus = event_bus or EventBus.get_instance()
        self._lock = threading.RLock()
        self._providers = providers or self._build_default_providers()
        self._provider_order = self._resolve_provider_order()
        self._active_provider: str | None = None
        self._sessions: dict[str, AIConversation] = {}
        self._prompts = PromptManager()
        self._metrics: dict[str, ProviderMetrics] = {
            name: ProviderMetrics() for name in self._providers
        }
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._started = False

    @classmethod
    def get_instance(
        cls,
        *,
        event_bus: EventBus | None = None,
        providers: dict[str, AIProvider] | None = None,
    ) -> AIManager:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(event_bus=event_bus, providers=providers)
            return cls._instance

    @classmethod
    def get_instance_optional(cls) -> AIManager | None:
        with cls._instance_lock:
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    @property
    def prompt_manager(self) -> PromptManager:
        return self._prompts

    @property
    def active_provider(self) -> str | None:
        return self._active_provider

    @property
    def provider_metrics(self) -> dict[str, ProviderMetrics]:
        with self._lock:
            return dict(self._metrics)

    def create_session(self, session_id: str | None = None) -> AIConversation:
        conversation = AIConversation.create(
            session_id=session_id,
            max_messages=settings.ai.conversation_memory,
        )
        with self._lock:
            self._sessions[conversation.session_id] = conversation
        return conversation

    def get_session(self, session_id: str) -> AIConversation | None:
        with self._lock:
            return self._sessions.get(session_id)

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._run_loop,
                name="ai-runtime-loop",
                daemon=True,
            )
            self._loop_thread.start()
            self._started = True
        self.run_coroutine(self._connect_providers())

    def shutdown(self) -> None:
        with self._lock:
            if not self._started:
                return
            loop = self._loop
            thread = self._loop_thread
            self._started = False
        if loop is not None:
            future = asyncio.run_coroutine_threadsafe(self._disconnect_providers(), loop)
            future.result(timeout=10)
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self._loop = None
            self._loop_thread = None
            self._sessions.clear()

    def run_coroutine(self, coro: Any) -> Any:
        loop = self._require_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=120)

    async def complete(
        self,
        session_id: str,
        user_message: str,
        *,
        template: str | None = None,
        include_camera: bool = True,
        include_audio: bool = True,
    ) -> AIResponse:
        request_id = str(uuid.uuid4())
        conversation = self._require_session(session_id)
        rendered = user_message
        conversation.add_message("user", rendered)
        messages = self._build_messages(
            conversation,
            include_camera=include_camera,
            include_audio=include_audio,
            system_template=template,
        )
        self._publish(AIRequestStarted(request_id=request_id, session_id=session_id, provider=self._active_provider or ""))
        started = time.perf_counter()
        try:
            response = await self._execute_with_failover(messages)
            conversation.add_message("assistant", response.text)
            self._record_success(response.provider, response)
            duration_ms = (time.perf_counter() - started) * 1000
            self._publish(
                AIRequestCompleted(
                    request_id=request_id,
                    session_id=session_id,
                    provider=response.provider,
                    duration_ms=duration_ms,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    total_tokens=response.total_tokens,
                )
            )
            return response
        except Exception as exc:
            self._record_failure(self._active_provider or settings.ai.provider)
            self._publish(
                AIRequestFailed(
                    request_id=request_id,
                    session_id=session_id,
                    provider=self._active_provider or settings.ai.provider,
                    error=str(exc),
                )
            )
            raise

    async def stream(
        self,
        session_id: str,
        user_message: str,
        *,
        template: str | None = None,
        include_camera: bool = True,
        include_audio: bool = True,
    ) -> AsyncIterator[AIStreamChunk]:
        request_id = str(uuid.uuid4())
        conversation = self._require_session(session_id)
        rendered = user_message
        conversation.add_message("user", rendered)
        messages = self._build_messages(
            conversation,
            include_camera=include_camera,
            include_audio=include_audio,
            system_template=template,
        )
        self._publish(
            AIRequestStarted(request_id=request_id, session_id=session_id, provider=self._active_provider or "")
        )
        self._publish(
            AIResponseStreamStarted(
                request_id=request_id,
                session_id=session_id,
                provider=self._active_provider or settings.ai.provider,
            )
        )
        started = time.perf_counter()
        collected: list[str] = []
        provider_name = self._active_provider or settings.ai.provider
        try:
            async for chunk in self._stream_with_failover(messages):
                provider_name = chunk.provider or provider_name
                if chunk.text:
                    collected.append(chunk.text)
                yield chunk
            final_text = "".join(collected)
            conversation.add_message("assistant", final_text)
            duration_ms = (time.perf_counter() - started) * 1000
            self._publish(
                AIResponseStreamCompleted(
                    request_id=request_id,
                    session_id=session_id,
                    provider=provider_name,
                    duration_ms=duration_ms,
                    total_tokens=max(len(final_text.split()), 1),
                )
            )
            self._publish(
                AIRequestCompleted(
                    request_id=request_id,
                    session_id=session_id,
                    provider=provider_name,
                    duration_ms=duration_ms,
                    prompt_tokens=0,
                    completion_tokens=max(len(final_text.split()), 1),
                    total_tokens=max(len(final_text.split()), 1),
                )
            )
        except Exception as exc:
            self._record_failure(provider_name)
            self._publish(
                AIRequestFailed(
                    request_id=request_id,
                    session_id=session_id,
                    provider=provider_name,
                    error=str(exc),
                )
            )
            raise

    def health_report(self) -> dict[str, Any]:
        with self._lock:
            metrics = {
                name: {
                    "requests": item.requests,
                    "failures": item.failures,
                    "total_tokens": item.total_tokens,
                    "average_latency_ms": round(item.average_latency_ms, 2),
                }
                for name, item in self._metrics.items()
            }
        return {
            "active_provider": self._active_provider,
            "providers": metrics,
            "sessions": len(self._sessions),
        }

    def _run_loop(self) -> None:
        loop = self._loop
        if loop is None:
            return
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _require_loop(self) -> asyncio.AbstractEventLoop:
        loop = self._loop
        if loop is None:
            raise RuntimeError("AI manager event loop is not running")
        return loop

    def _require_session(self, session_id: str) -> AIConversation:
        conversation = self.get_session(session_id)
        if conversation is None:
            raise KeyError(f"Unknown AI session: {session_id}")
        return conversation

    def _build_default_providers(self) -> dict[str, AIProvider]:
        return {
            "openai": OpenAIProvider(),
            "gemini": GeminiProvider(),
            "ollama": OllamaProvider(),
        }

    def _resolve_provider_order(self) -> list[str]:
        order = [settings.ai.provider, *settings.ai.fallback]
        seen: set[str] = set()
        resolved: list[str] = []
        for name in order:
            if name in self._providers and name not in seen:
                resolved.append(name)
                seen.add(name)
        return resolved

    async def _connect_providers(self) -> None:
        last_error: Exception | None = None
        for name in self._provider_order:
            provider = self._providers[name]
            try:
                await provider.connect()
                self._active_provider = name
                self._publish(AIProviderConnected(provider=name, model=provider.model))
                return
            except Exception as exc:
                last_error = exc
                self._publish(AIProviderDisconnected(provider=name, reason=str(exc)))
        if last_error is not None:
            raise ConnectionError(f"Unable to connect any AI provider: {last_error}") from last_error
        raise ConnectionError("No AI providers configured")

    async def _disconnect_providers(self) -> None:
        for name, provider in self._providers.items():
            try:
                await provider.disconnect()
                self._publish(AIProviderDisconnected(provider=name, reason="shutdown"))
            except Exception:
                continue
        self._active_provider = None

    async def _execute_with_failover(self, messages: tuple[Any, ...]) -> AIResponse:
        errors: list[str] = []
        for name in self._provider_order:
            provider = self._providers[name]
            if not await provider.is_available():
                try:
                    await provider.connect()
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                    continue
            try:
                response = await provider.complete(messages)
                self._active_provider = name
                return response
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                self._publish(AIProviderDisconnected(provider=name, reason=str(exc)))
                await provider.disconnect()
        raise RuntimeError("; ".join(errors) or "All AI providers failed")

    async def _stream_with_failover(self, messages: tuple[Any, ...]) -> AsyncIterator[AIStreamChunk]:
        errors: list[str] = []
        for name in self._provider_order:
            provider = self._providers[name]
            if not await provider.is_available():
                try:
                    await provider.connect()
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                    continue
            try:
                self._active_provider = name
                async for chunk in provider.stream(messages):
                    yield chunk
                return
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                self._publish(AIProviderDisconnected(provider=name, reason=str(exc)))
                await provider.disconnect()
        raise RuntimeError("; ".join(errors) or "All AI providers failed")

    def _build_messages(
        self,
        conversation: AIConversation,
        *,
        include_camera: bool,
        include_audio: bool,
        system_template: str | None = None,
    ) -> tuple[Any, ...]:
        from ottomandevice.plugins.ai.provider import AIMessage

        messages: list[AIMessage] = []
        system_parts: list[str] = []
        if system_template is not None:
            system_parts.append(
                self._prompts.render(system_template, hostname="ottoman-device", user_message="")
            )
        camera_context = self._camera_context() if include_camera else None
        audio_context = self._audio_context() if include_audio else None
        if camera_context:
            system_parts.append(camera_context)
        if audio_context:
            system_parts.append(audio_context)
        if system_parts:
            messages.append(AIMessage(role="system", content="\n".join(system_parts)))
        messages.extend(conversation.get_messages())
        return tuple(messages)

    def _camera_context(self) -> str | None:
        try:
            from ottomandevice.plugins.camera.manager import CameraManager

            manager = CameraManager.get_instance_optional()
            if manager is None or not manager.is_open:
                return None
            device_id = manager.active_device_id
            if device_id is None:
                return None
            from ottomandevice.config import settings as app_settings

            return self._prompts.render(
                "vision_context",
                camera_id=str(device_id),
                width=str(app_settings.camera.width),
                height=str(app_settings.camera.height),
            )
        except Exception:
            return None

    def _audio_context(self) -> str | None:
        try:
            from ottomandevice.plugins.audio.manager import AudioManager

            manager = AudioManager.get_instance_optional()
            if manager is None or not manager.is_open:
                return None
            device_id = manager.active_device_id
            if device_id is None:
                return None
            from ottomandevice.config import settings as app_settings

            return self._prompts.render(
                "audio_context",
                audio_id=str(device_id),
                sample_rate=str(app_settings.audio.sample_rate),
            )
        except Exception:
            return None

    def _record_success(self, provider_name: str, response: AIResponse) -> None:
        with self._lock:
            metrics = self._metrics.setdefault(provider_name, ProviderMetrics())
            metrics.requests += 1
            metrics.total_tokens += response.total_tokens
            metrics.total_latency_ms += response.latency_ms

    def _record_failure(self, provider_name: str) -> None:
        with self._lock:
            metrics = self._metrics.setdefault(provider_name, ProviderMetrics())
            metrics.failures += 1

    def _publish(self, event: Any) -> None:
        self._event_bus.publish(event)
