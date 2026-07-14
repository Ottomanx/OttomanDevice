from __future__ import annotations

import threading
from string import Template


class PromptManager:
    """Thread-safe prompt template registry and renderer."""

    def __init__(self) -> None:
        self._templates: dict[str, str] = {}
        self._lock = threading.RLock()
        self._register_defaults()

    def register_template(self, name: str, template: str) -> None:
        with self._lock:
            self._templates[name] = template

    def render(self, name: str, **variables: str) -> str:
        with self._lock:
            if name not in self._templates:
                raise KeyError(f"Unknown prompt template: {name}")
            template = Template(self._templates[name])
        return template.safe_substitute(**variables)

    def list_templates(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._templates))

    def _register_defaults(self) -> None:
        self.register_template(
            "device_assistant",
            "You are OttomanDevice assistant on $hostname. Be concise and helpful.",
        )
        self.register_template(
            "vision_context",
            "The device camera is active on index $camera_id with resolution ${width}x${height}.",
        )
        self.register_template(
            "audio_context",
            "The device microphone is active on index $audio_id at ${sample_rate}Hz.",
        )
