from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest

from ottomandevice.config.settings import AISettings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.core.plugin_manager import PluginManager
from ottomandevice.plugins.ai.conversation import AIConversation
from ottomandevice.plugins.ai.manager import AIManager
from ottomandevice.plugins.ai.plugin import OttomanAIPlugin
from ottomandevice.plugins.ai.prompts import PromptManager
from ottomandevice.plugins.ai.provider import AIMessage, AIProvider, AIResponse, AIStreamChunk


class MockAIProvider(AIProvider):
    def __init__(
        self,
        name: str,
        *,
        connect_error: Exception | None = None,
        complete_error: Exception | None = None,
        stream_error: Exception | None = None,
        response_text: str = "mock-response",
    ) -> None:
        self._name = name
        self._model = f"{name}-model"
        self._connect_error = connect_error
        self._complete_error = complete_error
        self._stream_error = stream_error
        self._response_text = response_text
        self._connected = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def model(self) -> str:
        return self._model

    async def connect(self) -> None:
        if self._connect_error is not None:
            raise self._connect_error
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    async def is_available(self) -> bool:
        return self._connected

    async def complete(
        self,
        messages: tuple[AIMessage, ...],
        *,
        model: str | None = None,
    ) -> AIResponse:
        if self._complete_error is not None:
            raise self._complete_error
        return AIResponse(
            text=self._response_text,
            provider=self._name,
            model=model or self._model,
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            latency_ms=12.5,
        )

    async def stream(
        self,
        messages: tuple[AIMessage, ...],
        *,
        model: str | None = None,
    ) -> AsyncIterator[AIStreamChunk]:
        if self._stream_error is not None:
            raise self._stream_error
        yield AIStreamChunk(text="mock-", done=False, provider=self._name)
        yield AIStreamChunk(text="stream", done=False, provider=self._name)
        yield AIStreamChunk(text="", done=True, provider=self._name)


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=200)
    yield event_bus
    event_bus.shutdown()


@pytest.fixture(autouse=True)
def reset_singletons() -> None:
    AIManager.reset_instance()
    PluginManager.reset_instance()
    yield
    AIManager.reset_instance()
    PluginManager.reset_instance()


@pytest.fixture
def ai_settings() -> AISettings:
    return AISettings(
        enabled=True,
        provider="openai",
        fallback=("gemini", "ollama"),
        streaming=True,
        conversation_memory=20,
    )


@pytest.fixture
def patched_settings(ai_settings: AISettings):
    patches = [
        patch("ottomandevice.plugins.ai.manager.settings"),
        patch("ottomandevice.plugins.ai.plugin.settings"),
    ]
    mocks = [item.start() for item in patches]
    for mock in mocks:
        mock.ai = ai_settings
    yield ai_settings
    for item in patches:
        item.stop()


@pytest.fixture
def providers() -> dict[str, MockAIProvider]:
    return {
        "openai": MockAIProvider("openai"),
        "gemini": MockAIProvider("gemini", response_text="gemini-response"),
        "ollama": MockAIProvider("ollama", response_text="ollama-response"),
    }


def _manager(bus: EventBus, providers: dict[str, MockAIProvider]) -> AIManager:
    return AIManager(event_bus=bus, providers=providers)


def test_prompt_manager_renders_template() -> None:
    prompts = PromptManager()
    rendered = prompts.render("device_assistant", hostname="test-host")
    assert "test-host" in rendered


def test_conversation_history_trim() -> None:
    conversation = AIConversation.create(max_messages=3)
    for index in range(5):
        conversation.add_message("user", f"message-{index}")
    messages = conversation.get_messages()
    assert len(messages) == 3
    assert messages[0].content == "message-2"


@pytest.mark.asyncio
async def test_provider_abstraction_complete(
    bus: EventBus, patched_settings, providers: dict[str, MockAIProvider]
) -> None:
    manager = _manager(bus, providers)
    manager.start()
    session = manager.create_session()
    response = await manager.complete(session.session_id, "hello")
    assert response.text == "mock-response"
    assert response.provider == "openai"
    manager.shutdown()


@pytest.mark.asyncio
async def test_provider_failover(
    bus: EventBus, patched_settings, providers: dict[str, MockAIProvider]
) -> None:
    providers["openai"] = MockAIProvider("openai", complete_error=RuntimeError("openai down"))
    manager = _manager(bus, providers)
    manager.start()
    session = manager.create_session()
    response = await manager.complete(session.session_id, "hello")
    assert response.provider == "gemini"
    assert response.text == "gemini-response"
    manager.shutdown()


@pytest.mark.asyncio
async def test_streaming_response(
    bus: EventBus, patched_settings, providers: dict[str, MockAIProvider]
) -> None:
    events: list[str] = []
    bus.subscribe("AIResponseStreamStarted", lambda event: events.append(event.event_type))
    bus.subscribe("AIResponseStreamCompleted", lambda event: events.append(event.event_type))

    manager = _manager(bus, providers)
    manager.start()
    session = manager.create_session()
    chunks: list[str] = []
    async for chunk in manager.stream(session.session_id, "hello"):
        if chunk.text:
            chunks.append(chunk.text)
    assert chunks == ["mock-", "stream"]
    assert events == ["AIResponseStreamStarted", "AIResponseStreamCompleted"]
    history = manager.get_session(session.session_id)
    assert history is not None
    assert history.get_messages()[-1].content == "mock-stream"
    manager.shutdown()


@pytest.mark.asyncio
async def test_conversation_history_persisted(
    bus: EventBus, patched_settings, providers: dict[str, MockAIProvider]
) -> None:
    manager = _manager(bus, providers)
    manager.start()
    session = manager.create_session()
    await manager.complete(session.session_id, "first")
    await manager.complete(session.session_id, "second")
    messages = manager.get_session(session.session_id).get_messages()
    assert len(messages) == 4
    assert messages[0].content == "first"
    assert messages[-1].role == "assistant"
    manager.shutdown()


def test_ai_events_on_request(
    bus: EventBus, patched_settings, providers: dict[str, MockAIProvider]
) -> None:
    events: list[str] = []
    bus.subscribe("AIRequestStarted", lambda event: events.append(event.event_type))
    bus.subscribe("AIRequestCompleted", lambda event: events.append(event.event_type))
    bus.subscribe("AIProviderConnected", lambda event: events.append(event.event_type))

    manager = _manager(bus, providers)
    manager.start()
    session = manager.create_session()
    manager.run_coroutine(manager.complete(session.session_id, "hello"))
    assert "AIProviderConnected" in events
    assert events.count("AIRequestStarted") == 1
    assert events.count("AIRequestCompleted") == 1
    manager.shutdown()


def test_ai_request_failed_event(
    bus: EventBus, patched_settings, providers: dict[str, MockAIProvider]
) -> None:
    for provider in providers.values():
        provider._complete_error = RuntimeError("failed")
        provider._stream_error = RuntimeError("failed")
    events: list[str] = []
    bus.subscribe("AIRequestFailed", lambda event: events.append(event.event_type))

    manager = _manager(bus, providers)
    manager.start()
    session = manager.create_session()
    with pytest.raises(RuntimeError):
        manager.run_coroutine(manager.complete(session.session_id, "hello"))
    assert events == ["AIRequestFailed"]
    manager.shutdown()


def test_plugin_starts_without_providers(bus: EventBus, patched_settings) -> None:
    failing = {
        "openai": MockAIProvider("openai", connect_error=ConnectionError("no key")),
        "gemini": MockAIProvider("gemini", connect_error=ConnectionError("no key")),
        "ollama": MockAIProvider("ollama", connect_error=ConnectionError("no key")),
    }
    plugin = OttomanAIPlugin()
    plugin.install()
    with patch.object(AIManager, "get_instance", return_value=AIManager(event_bus=bus, providers=failing)):
        plugin.initialize()
        plugin.start()
    plugin.stop()
    plugin.uninstall()


def test_plugin_metadata() -> None:
    plugin = OttomanAIPlugin()
    assert plugin.metadata.id == "ai"


def test_health_report_tracks_tokens(
    bus: EventBus, patched_settings, providers: dict[str, MockAIProvider]
) -> None:
    manager = _manager(bus, providers)
    manager.start()
    session = manager.create_session()
    manager.run_coroutine(manager.complete(session.session_id, "hello"))
    report = manager.health_report()
    assert report["active_provider"] == "openai"
    assert report["providers"]["openai"]["total_tokens"] == 15
    manager.shutdown()


def test_cloud_health_report(
    bus: EventBus, patched_settings, providers: dict[str, MockAIProvider]
) -> None:
    manager = _manager(bus, providers)
    manager.start()
    report = manager.health_report()
    assert report["providers"]["openai"]["requests"] >= 0
    manager.shutdown()
