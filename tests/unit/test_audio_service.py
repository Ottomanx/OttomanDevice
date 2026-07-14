from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import numpy as np
import pytest

from ottomandevice.config.settings import AudioSettings
from ottomandevice.core.event_bus import EventBus
from ottomandevice.core.health import HealthMonitor
from ottomandevice.core.plugin_manager import PluginManager
from ottomandevice.plugins.audio.backend import AudioBackendProtocol, InputDeviceInfo
from ottomandevice.plugins.audio.capture import AudioCapture, compute_input_level_db
from ottomandevice.plugins.audio.device import MicrophoneDevice
from ottomandevice.plugins.audio.health import AudioHealth
from ottomandevice.plugins.audio.manager import AudioManager
from ottomandevice.plugins.audio.plugin import OttomanAudioPlugin


class MockInputStream:
    def __init__(self, device_id: int, *, silent: bool = False, fail: bool = False) -> None:
        self.device_id = device_id
        self._silent = silent
        self._fail = fail
        self._running = False
        self.read_count = 0

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self._running = False

    def read(self, num_frames: int) -> tuple[Any, bool]:
        if not self._running or self._fail:
            return None, False
        self.read_count += 1
        amplitude = 100 if self._silent else 5000
        samples = np.full((num_frames, 1), amplitude, dtype=np.int16)
        overflowed = self.read_count % 5 == 0
        return samples, overflowed


class MockAudioBackend:
    def __init__(self) -> None:
        self._streams: dict[int, MockInputStream] = {}
        self._available = {0, 1}

    def query_input_devices(self) -> list[InputDeviceInfo]:
        return [
            InputDeviceInfo(0, "Mic 0", 1, 16000.0),
            InputDeviceInfo(1, "Mic 1", 2, 44100.0),
            InputDeviceInfo(2, "Output only", 0, 44100.0),
        ]

    def probe_input_device(self, device_id: int, *, sample_rate: int, channels: int) -> bool:
        return device_id in self._available

    def open_input_stream(
        self,
        device_id: int,
        *,
        sample_rate: int,
        channels: int,
        chunk_size: int,
    ) -> MockInputStream:
        if device_id not in self._available:
            raise OSError(f"device {device_id} unavailable")
        stream = MockInputStream(device_id)
        self._streams[device_id] = stream
        return stream

    def set_available(self, device_ids: set[int]) -> None:
        self._available = device_ids


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus(max_history=200)
    yield event_bus
    event_bus.shutdown()


@pytest.fixture(autouse=True)
def reset_singletons() -> None:
    AudioManager.reset_instance()
    HealthMonitor.clear_suppliers()
    PluginManager.reset_instance()
    yield
    AudioManager.reset_instance()
    HealthMonitor.clear_suppliers()
    PluginManager.reset_instance()


@pytest.fixture
def audio_settings() -> AudioSettings:
    return AudioSettings(
        enabled=True,
        device="auto",
        sample_rate=16000,
        channels=1,
        chunk_size=1024,
    )


@pytest.fixture
def patched_settings(audio_settings: AudioSettings):
    patches = [
        patch("ottomandevice.plugins.audio.manager.settings"),
        patch("ottomandevice.plugins.audio.plugin.settings"),
    ]
    mocks = [item.start() for item in patches]
    for mock in mocks:
        mock.audio = audio_settings
    yield audio_settings
    for item in patches:
        item.stop()


@pytest.fixture
def backend() -> MockAudioBackend:
    return MockAudioBackend()


def _manager(bus: EventBus, backend: MockAudioBackend) -> AudioManager:
    return AudioManager(
        event_bus=bus,
        backend=backend,
        hotplug_interval=0.05,
        silence_threshold_db=-20.0,
    )


def test_discover_microphones_publishes_detected_events(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    events: list[str] = []
    bus.subscribe("AudioDetected", lambda event: events.append(event.event_type))

    manager = _manager(bus, backend)
    discovered = manager.discover()

    assert discovered == [0, 1]
    assert events.count("AudioDetected") == 2


def test_auto_select_default_microphone(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    manager = _manager(bus, backend)
    manager.discover()
    assert manager.open("auto") is True
    assert manager.active_device_id == 0


def test_manual_device_selection(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    manager = _manager(bus, backend)
    manager.discover()
    assert manager.open(1) is True
    assert manager.active_device_id == 1


def test_open_close_microphone(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    events: list[str] = []
    bus.subscribe("AudioStarted", lambda event: events.append(event.event_type))
    bus.subscribe("AudioStopped", lambda event: events.append(event.event_type))

    manager = _manager(bus, backend)
    manager.discover()
    assert manager.open(0) is True
    manager.close()
    assert manager.is_open is False
    assert events == ["AudioStarted", "AudioStopped"]


def test_start_stop_recording(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    manager = _manager(bus, backend)
    manager.discover()
    manager.open(0)
    manager.start_recording()
    assert manager.is_recording is True
    assert manager.is_streaming is True
    time.sleep(0.12)
    manager.stop_recording()
    assert manager.is_streaming is False


def test_pcm_read_chunk(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    events: list[str] = []
    bus.subscribe("AudioFrameCaptured", lambda event: events.append(event.event_type))

    manager = _manager(bus, backend)
    manager.discover()
    manager.open(0)
    result = manager.read_chunk()

    assert result.success is True
    assert result.pcm is not None
    assert len(result.pcm) > 0
    assert events == ["AudioFrameCaptured"]


def test_sample_rate_and_channel_configuration(
    patched_settings, backend: MockAudioBackend
) -> None:
    device = MicrophoneDevice(
        0,
        sample_rate=8000,
        channels=1,
        chunk_size=512,
        backend=backend,
    )
    assert device.open() is True
    device.configure(sample_rate=16000, channels=1, chunk_size=1024)
    assert device.sample_rate == 16000
    assert device.chunk_size == 1024


def test_reconnect_after_disconnect(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    events: list[str] = []
    bus.subscribe("AudioDisconnected", lambda event: events.append(event.event_type))
    bus.subscribe("AudioReconnected", lambda event: events.append(event.event_type))

    manager = _manager(bus, backend)
    manager.discover()
    manager.open(0)
    backend._streams[0]._fail = True
    result = manager.read_chunk()
    assert result.success is False
    assert "AudioDisconnected" in events

    backend._streams.clear()
    backend.set_available({0})
    assert manager.attempt_reconnect() is True
    assert "AudioReconnected" in events


def test_silence_detection(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    events: list[str] = []
    bus.subscribe("AudioSilenceDetected", lambda event: events.append(event.event_type))

    backend.open_input_stream = lambda device_id, **kwargs: MockInputStream(device_id, silent=True)
    manager = _manager(bus, backend)
    manager.discover()
    manager.open(0)
    manager.read_chunk()

    assert "AudioSilenceDetected" in events


def test_input_level_monitoring(patched_settings, backend: MockAudioBackend) -> None:
    device = MicrophoneDevice(0, sample_rate=16000, channels=1, chunk_size=256, backend=backend)
    device.open()
    capture = AudioCapture(device, silence_threshold_db=-40.0)
    result = capture.read_single()
    assert result.input_level_db > -40.0


def test_buffer_overrun_detection(patched_settings, backend: MockAudioBackend) -> None:
    device = MicrophoneDevice(0, sample_rate=16000, channels=1, chunk_size=256, backend=backend)
    device.open()
    capture = AudioCapture(device)
    for _ in range(5):
        capture.read_single()
    assert capture.buffer_overruns >= 1


def test_health_monitoring_reports_metrics(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    manager = _manager(bus, backend)
    manager.register_health_monitor()
    manager.discover()
    manager.open(0)
    manager.read_chunk()

    report = HealthMonitor().collect()
    metric_names = {metric.name for metric in report.metrics}
    assert "audio_input_level_db" in metric_names
    assert "audio_buffer_overruns" in metric_names
    assert report.details.get("audio_connected") is True


def test_runtime_starts_without_microphone(bus: EventBus, patched_settings) -> None:
    plugin = OttomanAudioPlugin()
    plugin.install()
    plugin.initialize()
    with patch.object(AudioManager, "discover", return_value=[]):
        with patch.object(AudioManager, "open", return_value=False):
            plugin.start()
    assert plugin.manager is not None
    assert plugin.manager.is_open is False
    plugin.stop()
    plugin.uninstall()


def test_hot_plug_monitor_runs_discovery(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    manager = _manager(bus, backend)
    manager.discover()
    manager.start_hotplug_monitor()
    time.sleep(0.12)
    manager.stop_hotplug_monitor()
    assert manager.discovered_devices == (0, 1)


def test_audio_error_on_invalid_open(
    bus: EventBus, patched_settings, backend: MockAudioBackend
) -> None:
    operations: list[str] = []
    bus.subscribe("AudioError", lambda event: operations.append(event.payload.get("operation")))
    backend.set_available(set())
    manager = _manager(bus, backend)
    assert manager.open(99) is False
    assert operations == ["open"]


def test_audio_disabled_skips_open(bus: EventBus, audio_settings: AudioSettings, backend: MockAudioBackend) -> None:
    disabled = AudioSettings(
        enabled=False,
        device=audio_settings.device,
        sample_rate=audio_settings.sample_rate,
        channels=audio_settings.channels,
        chunk_size=audio_settings.chunk_size,
    )
    with patch("ottomandevice.plugins.audio.manager.settings") as mock_settings:
        mock_settings.audio = disabled
        manager = _manager(bus, backend)
        manager.discover()
        assert manager.open("auto") is False


def test_compute_input_level_db_silence() -> None:
    silent = np.zeros(128, dtype=np.int16)
    assert compute_input_level_db(silent) <= -90.0


def test_cloud_health_report(bus: EventBus, patched_settings, backend: MockAudioBackend) -> None:
    manager = _manager(bus, backend)
    manager.discover()
    manager.open(0)
    manager.read_chunk()
    report = manager.health_report()
    assert report["connected"] is True
    assert report["device_id"] == 0
    assert report["chunks_captured"] >= 1
