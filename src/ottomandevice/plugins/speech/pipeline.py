from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from ottomandevice.plugins.ai.provider import AIResponse
from ottomandevice.plugins.speech.buffer import AudioBuffer
from ottomandevice.plugins.speech.provider import TranscriptChunk
from ottomandevice.plugins.speech.vad import VoiceActivityDetector
from ottomandevice.plugins.speech.wake_word import WakeWordFramework


class SpeechPipeline:
    """End-to-end STT and TTS pipeline with optional AI integration."""

    def __init__(
        self,
        manager: Any,
        *,
        vad: VoiceActivityDetector | None = None,
        wake_words: WakeWordFramework | None = None,
    ) -> None:
        self._manager = manager
        self._vad = vad or VoiceActivityDetector()
        self._wake_words = wake_words or WakeWordFramework()
        self._input_buffer = AudioBuffer()
        self._playback_interrupt = asyncio.Event()
        self._playback_task: asyncio.Task[None] | None = None

    @property
    def wake_words(self) -> WakeWordFramework:
        return self._wake_words

    @property
    def input_buffer(self) -> AudioBuffer:
        return self._input_buffer

    async def ingest_audio(self, pcm: bytes) -> None:
        self._input_buffer.append(pcm)
        self._vad.process(pcm)

    async def recognize_buffered(self, *, language: str = "auto") -> str:
        pcm = self._input_buffer.drain()
        if not pcm:
            return ""
        result = await self._manager.transcribe_pcm(pcm, language=language)
        if result.text:
            self._wake_words.process_transcript(result.text)
        return result.text

    async def recognize_stream(self, *, language: str = "auto") -> AsyncIterator[TranscriptChunk]:
        async def chunk_source() -> AsyncIterator[bytes]:
            pcm = self._input_buffer.drain()
            if pcm:
                yield pcm

        async for chunk in self._manager.transcribe_stream(chunk_source(), language=language):
            if chunk.is_final and chunk.text:
                self._wake_words.process_transcript(chunk.text)
            yield chunk

    async def speak(self, text: str, *, language: str = "auto", interruptible: bool = True) -> None:
        await self.interrupt_playback()
        self._playback_interrupt.clear()

        async def _playback() -> None:
            await self._manager.play_text(text, language=language, interrupt_event=self._playback_interrupt)

        self._playback_task = asyncio.create_task(_playback())
        try:
            await self._playback_task
        except asyncio.CancelledError:
            if interruptible:
                raise

    async def interrupt_playback(self) -> None:
        self._playback_interrupt.set()
        if self._playback_task is not None and not self._playback_task.done():
            self._playback_task.cancel()
            try:
                await self._playback_task
            except asyncio.CancelledError:
                pass
        self._playback_task = None

    async def converse_with_ai(self, session_id: str, *, language: str = "auto") -> AIResponse:
        transcript = await self.recognize_buffered(language=language)
        if not transcript:
            raise RuntimeError("No speech recognized")
        ai_manager = self._manager.ai_manager
        if ai_manager is None:
            raise RuntimeError("AI runtime is not available")
        response = await ai_manager.complete(session_id, transcript)
        await self.speak(response.text, language=language)
        return response
