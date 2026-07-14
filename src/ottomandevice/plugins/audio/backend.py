from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class InputDeviceInfo:
    """Discovered microphone metadata."""

    device_id: int
    name: str
    max_input_channels: int
    default_sample_rate: float


class InputStreamProtocol(Protocol):
    """Blocking input stream contract."""

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def close(self) -> None: ...

    def read(self, num_frames: int) -> tuple[Any, bool]: ...


class AudioBackendProtocol(Protocol):
    """Cross-platform audio backend used by the microphone device."""

    def query_input_devices(self) -> list[InputDeviceInfo]: ...

    def probe_input_device(self, device_id: int, *, sample_rate: int, channels: int) -> bool: ...

    def open_input_stream(
        self,
        device_id: int,
        *,
        sample_rate: int,
        channels: int,
        chunk_size: int,
    ) -> InputStreamProtocol: ...


class SounddeviceBackend:
    """Production backend backed by the sounddevice PortAudio wrapper."""

    def query_input_devices(self) -> list[InputDeviceInfo]:
        import sounddevice as sd

        devices: list[InputDeviceInfo] = []
        for index, info in enumerate(sd.query_devices()):
            max_input = int(info.get("max_input_channels", 0))
            if max_input <= 0:
                continue
            devices.append(
                InputDeviceInfo(
                    device_id=index,
                    name=str(info.get("name", f"device-{index}")),
                    max_input_channels=max_input,
                    default_sample_rate=float(info.get("default_samplerate", 44100.0)),
                )
            )
        return devices

    def probe_input_device(self, device_id: int, *, sample_rate: int, channels: int) -> bool:
        import sounddevice as sd

        try:
            stream = sd.InputStream(
                device=device_id,
                samplerate=sample_rate,
                channels=channels,
                dtype="int16",
                blocksize=256,
            )
        except Exception:
            return False
        try:
            stream.start()
            stream.read(256)
            return True
        except Exception:
            return False
        finally:
            stream.stop()
            stream.close()

    def open_input_stream(
        self,
        device_id: int,
        *,
        sample_rate: int,
        channels: int,
        chunk_size: int,
    ) -> InputStreamProtocol:
        import sounddevice as sd

        return sd.InputStream(
            device=device_id,
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            blocksize=chunk_size,
        )


def default_audio_backend() -> AudioBackendProtocol:
    return SounddeviceBackend()
