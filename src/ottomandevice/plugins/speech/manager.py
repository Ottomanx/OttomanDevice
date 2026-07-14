from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ottomandevice.config import settings
from ottomandevice.core.event_bus import (
    EventBus,
    SpeechListeningStarted,
    SpeechListeningStopped,
    SpeechPlaybackCompleted,
    SpeechPlaybackInterrupted,
    SpeechPlaybackStarted,
    SpeechRecognized,
    SpeechRecognitionFailed,
)
from ottomandevice.plugins.speech.azure_provider import AzureSpeechProvider
from ottomandevice.plugins.speech.buffer import AudioBuffer
from ottomandevice.plugins.speech.elevenlabs_provider import ElevenLabsProvider
from ottomandevice.plugins.speech.pipeline import SpeechPipeline
from ottomandevice.plugins.speech.provider import (
    SpeechMetrics,
    STTProvider,
    SynthesisResult,
    TranscriptChunk,
    TranscriptionResult,
    TTSProvider,
)
from ottomandevice.plugins.speech.vad import VoiceActivityDetector
from ottomandevice.plugins.speech.whisper_provider import WhisperProvider
from ottomandevice.plugins.speech.wake_word import WakeWordFramework


class SpeechManager:
    """Orchestrates STT/TTS providers, streaming, failover, and AI integration."""

    _instance: SpeechManager | None = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        stt_providers: dict[str, STTProvider] | None = None,
        tts_providers: dict[str, TTSProvider] | None = None,
    ) -> None:
        self._event_bus = event_bus or EventBus.get_instance()
        self._lock = threading.RLock()
        self._stt_providers = stt_providers or self._build_default_stt_providers()
        self._tts_providers = tts_providers or self._build_default_tts_providers()
        self._stt_order = self._resolve_stt_order()
        self._tts_order = self._resolve_tts_order()
        self._active_stt: str | None = None
        self._active_tts: str | None = None
        self._metrics = SpeechMetrics()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._started = False
        self._listening = False
        self._playback_buffer = AudioBuffer(max_bytes=1024 * 512)
        self._pipeline = SpeechPipeline(
            self,
            vad=VoiceActivityDetector(),
            wake_words=WakeWordFramework(),
        )
        self._playback_interrupt = asyncio.Event()

    @classmethod
    def get_instance(
        cls,
        *,
        event_bus: EventBus | None = None,
        stt_providers: dict[str, STTProvider] | None = None,
        tts_providers: dict[str, TTSProvider] | None = None,
    ) -> SpeechManager:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(
                    event_bus=event_bus,
                    stt_providers=stt_providers,
                    tts_providers=tts_providers,
                )
            return cls._instance

    @classmethod
    def get_instance_optional(cls) -> SpeechManager | None:
        with cls._instance_lock:
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    @property
    def pipeline(self) -> SpeechPipeline:
        return self._pipeline

    @property
    def ai_manager(self) -> Any | None:
        try:
            from ottomandevice.plugins.ai.manager import AIManager

            return AIManager.get_instance_optional()
        except Exception:
            return None

    @property
    def is_listening(self) -> bool:
        with self._lock:
            return self._listening

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._loop = asyncio.new_event_loop()
            self._loop_thread = threading.Thread(
                target=self._run_loop,
                name="speech-runtime-loop",
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
            self._listening = False
        if loop is not None:
            future = asyncio.run_coroutine_threadsafe(self._disconnect_providers(), loop)
            future.result(timeout=10)
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self._loop = None
            self._loop_thread = None

    def run_coroutine(self, coro: Any) -> Any:
        loop = self._require_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=120)

    async def start_listening(self) -> None:
        with self._lock:
            if self._listening:
                return
            self._listening = True
        self._publish(SpeechListeningStarted(provider=self._active_stt or settings.speech.stt_provider))

    async def stop_listening(self) -> None:
        with self._lock:
            if not self._listening:
                return
            self._listening = False
        self._publish(SpeechListeningStopped(provider=self._active_stt or settings.speech.stt_provider))

    async def transcribe_pcm(self, pcm: bytes, *, language: str | None = None) -> TranscriptionResult:
        lang = language or settings.speech.language
        request_id = str(uuid.uuid4())
        try:
            result = await self._transcribe_with_failover(pcm, language=lang)
            self._metrics.stt_requests += 1
            self._metrics.stt_latency_ms += result.latency_ms
            self._publish(
                SpeechRecognized(
                    request_id=request_id,
                    text=result.text,
                    provider=result.provider,
                    confidence=result.confidence,
                    language=result.language,
                )
            )
            return result
        except Exception as exc:
            self._metrics.stt_failures += 1
            self._publish(
                SpeechRecognitionFailed(
                    request_id=request_id,
                    provider=self._active_stt or settings.speech.stt_provider,
                    error=str(exc),
                )
            )
            raise

    async def transcribe_stream(
        self,
        audio_chunks: AsyncIterator[bytes],
        *,
        language: str | None = None,
    ) -> AsyncIterator[TranscriptChunk]:
        lang = language or settings.speech.language
        provider = await self._select_stt_provider()
        async for chunk in provider.transcribe_stream(audio_chunks, language=lang):
            if chunk.is_final and chunk.text:
                self._publish(
                    SpeechRecognized(
                        request_id=str(uuid.uuid4()),
                        text=chunk.text,
                        provider=provider.name,
                        confidence=chunk.confidence,
                        language=chunk.language,
                    )
                )
            yield chunk

    async def synthesize_text(self, text: str, *, language: str | None = None) -> SynthesisResult:
        lang = language or settings.speech.language
        return await self._synthesize_with_failover(text, language=lang)

    async def play_text(
        self,
        text: str,
        *,
        language: str | None = None,
        interrupt_event: asyncio.Event | None = None,
    ) -> None:
        lang = language or settings.speech.language
        request_id = str(uuid.uuid4())
        self._publish(
            SpeechPlaybackStarted(
                request_id=request_id,
                provider=self._active_tts or settings.speech.tts_provider,
                text_length=len(text),
            )
        )
        started = time.perf_counter()
        interrupted = False
        try:
            if settings.speech.streaming:
                async for chunk in self._synthesize_stream_with_failover(text, language=lang):
                    if interrupt_event is not None and interrupt_event.is_set():
                        interrupted = True
                        break
                    if chunk.audio:
                        self._playback_buffer.append(chunk.audio)
            else:
                result = await self._synthesize_with_failover(text, language=lang)
                self._playback_buffer.append(result.audio)
            duration_ms = (time.perf_counter() - started) * 1000
            if interrupted:
                self._publish(
                    SpeechPlaybackInterrupted(
                        request_id=request_id,
                        provider=self._active_tts or settings.speech.tts_provider,
                        duration_ms=duration_ms,
                    )
                )
            else:
                self._publish(
                    SpeechPlaybackCompleted(
                        request_id=request_id,
                        provider=self._active_tts or settings.speech.tts_provider,
                        duration_ms=duration_ms,
                        bytes_played=self._playback_buffer.size,
                    )
                )
        except Exception as exc:
            self._metrics.tts_failures += 1
            raise RuntimeError(str(exc)) from exc

    def ingest_microphone_chunk(self, pcm: bytes) -> None:
        if not self.is_listening:
            return
        self.run_coroutine(self._pipeline.ingest_audio(pcm))

    def health_report(self) -> dict[str, Any]:
        return {
            "active_stt": self._active_stt,
            "active_tts": self._active_tts,
            "listening": self.is_listening,
            "metrics": {
                "stt_requests": self._metrics.stt_requests,
                "tts_requests": self._metrics.tts_requests,
                "stt_failures": self._metrics.stt_failures,
                "tts_failures": self._metrics.tts_failures,
                "average_stt_latency_ms": round(self._metrics.average_stt_latency_ms, 2),
                "average_tts_latency_ms": round(self._metrics.average_tts_latency_ms, 2),
            },
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
            raise RuntimeError("Speech manager event loop is not running")
        return loop

    def _build_default_stt_providers(self) -> dict[str, STTProvider]:
        azure = AzureSpeechProvider()
        return {"whisper": WhisperProvider(), "azure": azure}

    def _build_default_tts_providers(self) -> dict[str, TTSProvider]:
        azure = AzureSpeechProvider()
        return {"elevenlabs": ElevenLabsProvider(), "azure": azure}

    def _resolve_stt_order(self) -> list[str]:
        order = [settings.speech.stt_provider, *settings.speech.stt_fallback]
        return self._dedupe_provider_order(order, self._stt_providers)

    def _resolve_tts_order(self) -> list[str]:
        order = [settings.speech.tts_provider, *settings.speech.tts_fallback]
        return self._dedupe_provider_order(order, self._tts_providers)

    @staticmethod
    def _dedupe_provider_order(order: list[str], providers: dict[str, Any]) -> list[str]:
        seen: set[str] = set()
        resolved: list[str] = []
        for name in order:
            if name in providers and name not in seen:
                resolved.append(name)
                seen.add(name)
        return resolved

    async def _connect_providers(self) -> None:
        await self._connect_first_available(self._stt_order, self._stt_providers, kind="stt")
        await self._connect_first_available(self._tts_order, self._tts_providers, kind="tts")

    async def _disconnect_providers(self) -> None:
        for provider in self._stt_providers.values():
            try:
                await provider.disconnect()
            except Exception:
                continue
        for provider in self._tts_providers.values():
            try:
                await provider.disconnect()
            except Exception:
                continue
        self._active_stt = None
        self._active_tts = None

    async def _connect_first_available(
        self,
        order: list[str],
        providers: dict[str, Any],
        *,
        kind: str,
    ) -> None:
        for name in order:
            provider = providers[name]
            try:
                await provider.connect()
                if kind == "stt":
                    self._active_stt = name
                else:
                    self._active_tts = name
                return
            except Exception:
                continue

    async def _select_stt_provider(self) -> STTProvider:
        for name in self._stt_order:
            provider = self._stt_providers[name]
            if not await provider.is_available():
                try:
                    await provider.connect()
                except Exception:
                    continue
            self._active_stt = name
            return provider
        raise RuntimeError("No STT provider available")

    async def _select_tts_provider(self) -> TTSProvider:
        for name in self._tts_order:
            provider = self._tts_providers[name]
            if not await provider.is_available():
                try:
                    await provider.connect()
                except Exception:
                    continue
            self._active_tts = name
            return provider
        raise RuntimeError("No TTS provider available")

    async def _transcribe_with_failover(self, pcm: bytes, *, language: str) -> TranscriptionResult:
        errors: list[str] = []
        for name in self._stt_order:
            provider = self._stt_providers[name]
            try:
                if not await provider.is_available():
                    await provider.connect()
                result = await provider.transcribe(pcm, language=language)
                self._active_stt = name
                return result
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                await provider.disconnect()
        raise RuntimeError("; ".join(errors) or "STT providers failed")

    async def _synthesize_with_failover(self, text: str, *, language: str) -> SynthesisResult:
        errors: list[str] = []
        for name in self._tts_order:
            provider = self._tts_providers[name]
            try:
                if not await provider.is_available():
                    await provider.connect()
                started = time.perf_counter()
                result = await provider.synthesize(text, language=language)
                self._active_tts = name
                self._metrics.tts_requests += 1
                self._metrics.tts_latency_ms += result.latency_ms
                return result
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                await provider.disconnect()
        raise RuntimeError("; ".join(errors) or "TTS providers failed")

    async def _synthesize_stream_with_failover(
        self,
        text: str,
        *,
        language: str,
    ) -> AsyncIterator[Any]:
        errors: list[str] = []
        for name in self._tts_order:
            provider = self._tts_providers[name]
            try:
                if not await provider.is_available():
                    await provider.connect()
                self._active_tts = name
                self._metrics.tts_requests += 1
                async for chunk in provider.synthesize_stream(text, language=language):
                    yield chunk
                return
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                await provider.disconnect()
        raise RuntimeError("; ".join(errors) or "TTS providers failed")

    def _publish(self, event: Any) -> None:
        self._event_bus.publish(event)
