from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = CONFIG_DIR / "default.yaml"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass(frozen=True)
class StorageSettings:
    screenshots_bucket: str
    desktop_bucket: str
    screenshots_dir: str


@dataclass(frozen=True)
class HeartbeatSettings:
    interval: int


@dataclass(frozen=True)
class TelemetrySettings:
    interval: int


@dataclass(frozen=True)
class DesktopSettings:
    capture_interval: float
    jpeg_quality: int
    width: int
    latest_frame_name: str


@dataclass(frozen=True)
class CameraSettings:
    enabled: bool
    device: str
    width: int
    height: int
    fps: int
    windows_backend: str
    default_backend: str
    detection_range: int




@dataclass(frozen=True)
class AudioSettings:
    enabled: bool
    device: str
    sample_rate: int
    channels: int
    chunk_size: int

@dataclass(frozen=True)
class FirmwareSettings:
    version: str


@dataclass(frozen=True)
class OtaSettings:
    check_interval: int
    download_dir: str
    active_dir: str
    backup_dir: str
    firmware_bucket: str
    signing_secret_env: str


@dataclass(frozen=True)
class CommandSettings:
    poll_interval: int


@dataclass(frozen=True)
class FileTransferSettings:
    workspace_dir: str
    max_file_size_bytes: int
    chunk_size: int
    partial_dir: str = "data/transfers/partials"
    manifest_dir: str = "data/transfers/manifests"
    fsync_interval_bytes: int = 4194304
    worker_count: int = 2
    allow_overwrite: bool = False


@dataclass(frozen=True)
class RemoteDesktopSettings:
    host: str
    port: int
    path: str
    subprotocol: str
    ping_interval: int
    disconnect_timeout: int
    token_ttl_seconds: int
    jwt_secret_env: str
    jwt_algorithm: str
    fps: int
    jpeg_quality: int
    width: int
    clipboard_poll_interval_ms: int
    file_transfer: FileTransferSettings
    monitor_poll_interval_streaming_ms: int = 1000
    monitor_poll_interval_idle_ms: int = 5000
    monitor_switch_immediate_capture: bool = True


@dataclass(frozen=True)
class Settings:
    storage: StorageSettings
    heartbeat: HeartbeatSettings
    telemetry: TelemetrySettings
    desktop: DesktopSettings
    camera: CameraSettings
    audio: AudioSettings
    firmware: FirmwareSettings
    ota: OtaSettings
    command: CommandSettings
    remote_desktop: RemoteDesktopSettings

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        remote_desktop_data = data["remote_desktop"]
        file_transfer_data = remote_desktop_data.get(
            "file_transfer",
            {
                "workspace_dir": "data/workspace",
                "max_file_size_bytes": 104857600,
                "chunk_size": 65536,
                "partial_dir": "data/transfers/partials",
                "manifest_dir": "data/transfers/manifests",
                "fsync_interval_bytes": 4194304,
                "worker_count": 2,
                "allow_overwrite": False,
            },
        )
        return cls(
            storage=StorageSettings(**data["storage"]),
            heartbeat=HeartbeatSettings(**data["heartbeat"]),
            telemetry=TelemetrySettings(**data["telemetry"]),
            desktop=DesktopSettings(**data["desktop"]),
            camera=CameraSettings(
                enabled=bool(data["camera"].get("enabled", True)),
                device=str(data["camera"].get("device", "auto")),
                width=int(data["camera"].get("width", 1280)),
                height=int(data["camera"].get("height", 720)),
                fps=int(data["camera"].get("fps", 30)),
                windows_backend=data["camera"]["windows_backend"],
                default_backend=data["camera"]["default_backend"],
                detection_range=int(data["camera"]["detection_range"]),
            ),
            audio=AudioSettings(
                enabled=bool(data.get("audio", {}).get("enabled", True)),
                device=str(data.get("audio", {}).get("device", "auto")),
                sample_rate=int(data.get("audio", {}).get("sample_rate", 16000)),
                channels=int(data.get("audio", {}).get("channels", 1)),
                chunk_size=int(data.get("audio", {}).get("chunk_size", 1024)),
            ),
            firmware=FirmwareSettings(**data["firmware"]),
            ota=OtaSettings(**data.get("ota", {
                "check_interval": 300,
                "download_dir": "data/ota",
                "active_dir": "data/ota/active",
                "backup_dir": "data/ota/backup",
                "firmware_bucket": "firmware",
                "signing_secret_env": "OTA_SIGNING_SECRET",
            })),
            command=CommandSettings(**data["command"]),
            remote_desktop=RemoteDesktopSettings(
                host=remote_desktop_data["host"],
                port=remote_desktop_data["port"],
                path=remote_desktop_data["path"],
                subprotocol=remote_desktop_data["subprotocol"],
                ping_interval=remote_desktop_data["ping_interval"],
                disconnect_timeout=remote_desktop_data["disconnect_timeout"],
                token_ttl_seconds=remote_desktop_data["token_ttl_seconds"],
                jwt_secret_env=remote_desktop_data["jwt_secret_env"],
                jwt_algorithm=remote_desktop_data["jwt_algorithm"],
                fps=remote_desktop_data["fps"],
                jpeg_quality=remote_desktop_data["jpeg_quality"],
                width=remote_desktop_data["width"],
                clipboard_poll_interval_ms=remote_desktop_data.get(
                    "clipboard_poll_interval_ms",
                    300,
                ),
                monitor_poll_interval_streaming_ms=remote_desktop_data.get(
                    "monitor_poll_interval_streaming_ms",
                    1000,
                ),
                monitor_poll_interval_idle_ms=remote_desktop_data.get(
                    "monitor_poll_interval_idle_ms",
                    5000,
                ),
                monitor_switch_immediate_capture=remote_desktop_data.get(
                    "monitor_switch_immediate_capture",
                    True,
                ),
                file_transfer=FileTransferSettings(**file_transfer_data),
            ),
        )


def _read_yaml(path: Path) -> dict[str, Any]:
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            content = path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

        parsed = yaml.safe_load(content)
        return parsed or {}

    raise ValueError(f"Unable to read config file: {path}")


def load_settings(config_path: Path | None = None) -> Settings:
    raw = _read_yaml(DEFAULT_CONFIG_PATH)

    override_path = config_path
    if override_path is None:
        env_path = os.getenv("OTTOMAN_CONFIG_PATH")
        if env_path:
            override_path = Path(env_path)

    if override_path and override_path.exists():
        override = _read_yaml(override_path)
        raw = _deep_merge(raw, override)

    return Settings.from_dict(raw)


settings = load_settings()
