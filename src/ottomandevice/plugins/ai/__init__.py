"""AI runtime plugin package for OttomanDevice."""

from ottomandevice.plugins.ai.conversation import AIConversation
from ottomandevice.plugins.ai.gemini_provider import GeminiProvider
from ottomandevice.plugins.ai.manager import AIManager
from ottomandevice.plugins.ai.ollama_provider import OllamaProvider
from ottomandevice.plugins.ai.openai_provider import OpenAIProvider
from ottomandevice.plugins.ai.plugin import OttomanAIPlugin
from ottomandevice.plugins.ai.prompts import PromptManager
from ottomandevice.plugins.ai.provider import AIProvider, AIMessage, AIResponse, AIStreamChunk

plugin_class = OttomanAIPlugin

__all__ = [
    "AIConversation",
    "AIManager",
    "AIMessage",
    "AIProvider",
    "AIResponse",
    "AIStreamChunk",
    "GeminiProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "OttomanAIPlugin",
    "PromptManager",
    "plugin_class",
]
