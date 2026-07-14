from __future__ import annotations

import threading
import time
from typing import Any

from ottomandevice.config import settings
from ottomandevice.core.event_bus import (
    AudioDetected,
    AudioDisconnected,
    AudioError,
    AudioFrameCaptured,
    AudioReconnected,
    AudioSilenceDetected,
    AudioStarted,
    AudioStopped,
    EventBus,
)
from ottomandevice.core.health import HealthMonitor
from ottomandevice.plugins.audio.backend import AudioBackendProtocol, default_audio_backend
from ottomandevice.plugins.audio.capture import AudioCapture, ChunkResult
from ottomandevice.plugins.audio.device import MicrophoneDevice
from ottomandevice.plugins.audio.health import AudioHealth

HOTPLUG_INTERVAL_SECONDS = 3.0
RECONNECT_BASE_DELAY_SECONDS = 1.0
RECONNECT_MAX_DELAY_SECONDS = 30.0


class AudioManager:
    """Orchestrates microphone discovery, capture, health, and hot-plug handling."""

    _instance: AudioManager | None = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        backend: AudioBackendProtocol | None = None,
        hotplug_interval: float = HOTPLUG_INTERVAL_SECONDS,
        silence_threshold_db: float = -40.0,
    ) -> None:
        self._event_bus = event_bus or EventBus.get_instance()
        self._backend = backend or default_audio_backend()
        self._hotplug_interval = hotplug_interval
        self._silence_threshold_db = silence_threshold_db
        self._lock = threading.RLock()
        self._device: MicrophoneDevice | None = None
        self._capture: AudioCapture | None = None
        self._health = AudioHealth(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )
        self._discovered: list[int] = []
        self._selected_device: int | str = settings.audio.device
        self._hotplug_thread: threading.Thread | None = None
        self._hotplug_stop = threading.Event()
        self._reconnect_delay = RECONNECT_BASE_DELAY_SECONDS
        self._health_supplier_registered = False
        self._recording = False

    @classmethod
    def get_instance(
        cls,
        *,
        event_bus: EventBus | None = None,
        backend: AudioBackendProtocol | None = None,
    ) -> AudioManager:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls(event_bus=event_bus, backend=backend)
            return cls._instance

    @classmethod
    def get_instance_optional(cls) -> AudioManager | None:
        with cls._instance_lock:
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance.shutdown()
            cls._instance = None

    @property
    def health(self) -> AudioHealth:
        return self._health

    @property
    def discovered_devices(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(self._discovered)

    @property
    def active_device_id(self) -> int | None:
        with self._lock:
            return self._device.device_id if self._device is not None else None

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._device is not None and self._device.is_open

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording

    @property
    def is_streaming(self) -> bool:
        with self._lock:
            return self._capture is not None and self._capture.is_streaming

    def register_health_monitor(self) -> None:
        if self._health_supplier_registered:
            return
        HealthMonitor.register_supplier(self._health.to_metrics)
        self._health_supplier_registered = True

    def unregister_health_monitor(self) -> None:
        if not self._health_supplier_registered:
            return
        HealthMonitor.unregister_supplier(self._health.to_metrics)
        self._health_supplier_registered = False

    def discover(self) -> list[int]:
        available: list[int] = []
        for info in self._backend.query_input_devices():
            if self._backend.probe_input_device(
                info.device_id,
                sample_rate=settings.audio.sample_rate,
                channels=min(settings.audio.channels, info.max_input_channels),
            ):
                available.append(info.device_id)
                self._publish(
                    AudioDetected(
                        device_id=info.device_id,
                        name=info.name,
                        sample_rate=settings.audio.sample_rate,
                        channels=settings.audio.channels,
                    )
                )

        with self._lock:
            previous = set(self._discovered)
            current = set(available)
            self._discovered = available
            active_id = self._device.device_id if self._device is not None else None
            if active_id is not None and active_id not in current:
                self._handle_disconnect(f"Microphone index {active_id} no longer available")

        return available

    def select_device(self, device: int | str) -> None:
        with self._lock:
            self._selected_device = device

    def open(self, device: int | str | None = None) -> bool:
        if not settings.audio.enabled:
            return False

        target = device if device is not None else self._selected_device
        device_id = self._resolve_device_id(target)
        if device_id is None:
            return False

        if self.is_open and self.active_device_id == device_id:
            return True

        self.close()
        microphone = MicrophoneDevice(
            device_id,
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
            chunk_size=settings.audio.chunk_size,
            backend=self._backend,
        )
        if not microphone.open():
            self._publish_error(device_id, "open", "Unable to open microphone device")
            return False

        capture = AudioCapture(
            microphone,
            silence_threshold_db=self._silence_threshold_db,
        )
        capture.set_chunk_event_handler(self._on_chunk_captured)

        with self._lock:
            self._device = microphone
            self._capture = capture
            self._reconnect_delay = RECONNECT_BASE_DELAY_SECONDS

        self._health.set_format(
            sample_rate=settings.audio.sample_rate,
            channels=settings.audio.channels,
        )
        self._health.set_device(device_id, connected=True)
        self._health.record_reconnect(device_id)
        self._publish(
            AudioStarted(
                device_id=device_id,
                sample_rate=settings.audio.sample_rate,
                channels=settings.audio.channels,
            )
        )
        return True

    def close(self) -> None:
        self.stop_recording()
        with self._lock:
            device = self._device
            capture = self._capture
            self._device = None
            self._capture = None

        if capture is not None:
            capture.stop_stream()
        if device is not None:
            device_id = device.device_id
            device.close()
            self._health.set_device(device_id, connected=False)
            self._health.record_disconnect()
            self._publish(AudioStopped(device_id=device_id))

    def start_recording(self) -> None:
        """Start PCM streaming from the open microphone."""
        with self._lock:
            capture = self._capture
        if capture is None:
            self._publish_error(-1, "record", "Microphone is not open")
            return
        capture.start_stream()
        with self._lock:
            self._recording = True

    def stop_recording(self) -> None:
        with self._lock:
            capture = self._capture
            self._recording = False
        if capture is not None:
            capture.stop_stream()

    def read_chunk(self) -> ChunkResult:
        with self._lock:
            capture = self._capture
            device_id = self._device.device_id if self._device is not None else -1
        if capture is None:
            result = ChunkResult(
                success=False,
                pcm=None,
                chunk_number=0,
                sample_rate=settings.audio.sample_rate,
                channels=settings.audio.channels,
                input_level_db=-100.0,
                silent=True,
                overflowed=False,
            )
            self._publish_error(device_id, "capture", "Microphone is not open")
            return result

        result = capture.read_single()
        if not result.success:
            self._handle_disconnect("PCM capture failed")
        return result

    def configure(self, *, sample_rate: int, channels: int, chunk_size: int) -> None:
        with self._lock:
            device = self._device
        if device is not None:
            device.configure(sample_rate=sample_rate, channels=channels, chunk_size=chunk_size)
            self._health.set_format(sample_rate=sample_rate, channels=channels)

    def start_hotplug_monitor(self) -> None:
        with self._lock:
            if self._hotplug_thread is not None and self._hotplug_thread.is_alive():
                return
            self._hotplug_stop.clear()
            self._hotplug_thread = threading.Thread(
                target=self._hotplug_loop,
                name="audio-hotplug",
                daemon=True,
            )
            self._hotplug_thread.start()

    def stop_hotplug_monitor(self) -> None:
        self._hotplug_stop.set()
        with self._lock:
            thread = self._hotplug_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._hotplug_interval + 2)
        with self._lock:
            self._hotplug_thread = None

    def attempt_reconnect(self) -> bool:
        device = self._selected_device
        if self.open(device):
            device_id = self.active_device_id
            if device_id is not None:
                self._publish(AudioReconnected(device_id=device_id))
            self._reconnect_delay = RECONNECT_BASE_DELAY_SECONDS
            return True
        self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_MAX_DELAY_SECONDS)
        return False

    def health_report(self) -> dict[str, Any]:
        with self._lock:
            capture = self._capture
        if capture is not None:
            self._sync_health_counters(capture)
        return self._health.to_cloud_dict()

    def shutdown(self) -> None:
        self.stop_hotplug_monitor()
        self.close()
        self.unregister_health_monitor()

    def _hotplug_loop(self) -> None:
        while not self._hotplug_stop.wait(self._hotplug_interval):
            try:
                self.discover()
                if not self.is_open and settings.audio.enabled:
                    if self._selected_device == "auto" and self._discovered:
                        self.open("auto")
                    elif self._should_reconnect():
                        time.sleep(self._reconnect_delay)
                        self.attempt_reconnect()
            except Exception as exc:
                self._publish_error(self.active_device_id or -1, "hotplug", str(exc))

    def _should_reconnect(self) -> bool:
        with self._lock:
            if self._selected_device == "auto":
                return bool(self._discovered)
            if isinstance(self._selected_device, int):
                return self._selected_device in self._discovered
            if str(self._selected_device).isdigit():
                return int(self._selected_device) in self._discovered
            return False

    def _resolve_device_id(self, target: int | str) -> int | None:
        if isinstance(target, int):
            return target
        if str(target).isdigit():
            return int(target)
        if str(target) == "auto":
            if not self._discovered:
                self.discover()
            return self._discovered[0] if self._discovered else None
        return None

    def _handle_disconnect(self, reason: str) -> None:
        device_id = self.active_device_id
        self.close()
        if device_id is not None:
            self._publish(AudioDisconnected(device_id=device_id, reason=reason))

    def _on_chunk_captured(self, result: ChunkResult) -> None:
        if not result.success:
            self._health.record_chunk(success=False, input_level_db=-100.0)
            self._handle_disconnect("Streaming PCM read failed")
            return
        self._process_chunk_result(result)

    def _process_chunk_result(self, result: ChunkResult) -> None:
        self._health.record_chunk(
            success=True,
            input_level_db=result.input_level_db,
            silent=result.silent,
            overflowed=result.overflowed,
        )
        if result.silent:
            self._publish(
                AudioSilenceDetected(
                    device_id=self.active_device_id or -1,
                    input_level_db=result.input_level_db,
                )
            )
        with self._lock:
            capture = self._capture
        if capture is not None:
            self._sync_health_counters(capture)

        pcm_bytes = len(result.pcm) if result.pcm is not None else 0
        self._publish(
            AudioFrameCaptured(
                device_id=self.active_device_id or -1,
                chunk_number=result.chunk_number,
                sample_rate=result.sample_rate,
                channels=result.channels,
                bytes_length=pcm_bytes,
                input_level_db=result.input_level_db,
                streaming=result.streaming,
            )
        )

    def _sync_health_counters(self, capture: AudioCapture) -> None:
        self._health.sync_capture_stats(
            chunks_captured=capture.chunk_count,
            buffer_overruns=capture.buffer_overruns,
            input_level_db=capture.latest_level_db,
        )

    def _publish(self, event: Any) -> None:
        self._event_bus.publish(event)

    def _publish_error(self, device_id: int, operation: str, error: str) -> None:
        self._health.record_error(error)
        self._publish(AudioError(device_id=device_id, operation=operation, error=error))
