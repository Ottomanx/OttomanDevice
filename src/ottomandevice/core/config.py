from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ottomandevice.config.settings import DEFAULT_CONFIG_PATH, Settings
from ottomandevice.core.exceptions import ConfigurationError

ENV_PREFIX = "OTTOMAN_"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = base.copy()
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    for encoding in ("utf-8-sig", "utf-8", "utf-16"):
        try:
            content = path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue

        parsed = yaml.safe_load(content)
        return parsed or {}

    raise ConfigurationError(f"Unable to read config file: {path}")


def _flatten_env_key(key: str) -> str:
    return key.removeprefix(ENV_PREFIX).lower()


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    merged = raw.copy()
    for env_key, value in os.environ.items():
        if not env_key.startswith(ENV_PREFIX) or env_key == "OTTOMAN_CONFIG_PATH":
            continue

        parts = _flatten_env_key(env_key).split("__")
        cursor: dict[str, Any] = merged
        for part in parts[:-1]:
            existing = cursor.get(part)
            if not isinstance(existing, dict):
                existing = {}
                cursor[part] = existing
            cursor = existing

        leaf = parts[-1]
        if value.lower() in {"true", "false"}:
            cursor[leaf] = value.lower() == "true"
        else:
            try:
                if "." in value:
                    cursor[leaf] = float(value)
                else:
                    cursor[leaf] = int(value)
            except ValueError:
                cursor[leaf] = value
    return merged


@dataclass(frozen=True)
class RuntimeConfig:
    """Core runtime tuning values."""

    log_level: str
    log_dir: str
    max_log_bytes: int
    log_backup_count: int
    supervisor_restart_delay_seconds: float
    supervisor_max_restarts: int
    health_check_interval_seconds: float


class ConfigManager:
    """Singleton configuration loader for YAML, environment, and defaults."""

    _instance: ConfigManager | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._raw: dict[str, Any] = {}
        self._settings: Settings | None = None
        self._runtime: RuntimeConfig | None = None
        self._loaded = False

    @classmethod
    def get_instance(cls) -> ConfigManager:
        """Return the process-wide configuration manager singleton."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def load(self, config_path: Path | None = None) -> Settings:
        """Load and merge configuration sources.

        Args:
            config_path: Optional explicit YAML override path.

        Returns:
            Parsed application settings.
        """
        raw = _read_yaml(DEFAULT_CONFIG_PATH)

        override_path = config_path
        if override_path is None:
            env_path = os.getenv("OTTOMAN_CONFIG_PATH")
            if env_path:
                override_path = Path(env_path)

        if override_path and override_path.exists():
            raw = _deep_merge(raw, _read_yaml(override_path))

        raw = _apply_env_overrides(raw)
        self._raw = raw
        self._settings = Settings.from_dict(raw)
        self._runtime = self._build_runtime_config(raw.get("runtime", {}))
        self._loaded = True
        return self._settings

    def reload(self, config_path: Path | None = None) -> Settings:
        """Reload configuration from disk and environment."""
        return self.load(config_path=config_path)

    @property
    def settings(self) -> Settings:
        """Return loaded application settings."""
        if not self._loaded or self._settings is None:
            return self.load()
        return self._settings

    @property
    def runtime(self) -> RuntimeConfig:
        """Return loaded runtime settings."""
        if not self._loaded or self._runtime is None:
            self.load()
        assert self._runtime is not None
        return self._runtime

    def get(self, *path: str, default: Any = None) -> Any:
        """Read a nested configuration value by key path."""
        cursor: Any = self._raw
        if not self._loaded:
            self.load()

        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                return default
            cursor = cursor[key]
        return cursor

    def as_dict(self) -> dict[str, Any]:
        """Return the merged raw configuration dictionary."""
        if not self._loaded:
            self.load()
        return dict(self._raw)

    def _build_runtime_config(self, runtime_data: Any) -> RuntimeConfig:
        data = runtime_data if isinstance(runtime_data, dict) else {}
        return RuntimeConfig(
            log_level=str(data.get("log_level", "INFO")),
            log_dir=str(data.get("log_dir", "logs")),
            max_log_bytes=int(data.get("max_log_bytes", 5 * 1024 * 1024)),
            log_backup_count=int(data.get("log_backup_count", 5)),
            supervisor_restart_delay_seconds=float(
                data.get("supervisor_restart_delay_seconds", 5.0)
            ),
            supervisor_max_restarts=int(data.get("supervisor_max_restarts", 10)),
            health_check_interval_seconds=float(
                data.get("health_check_interval_seconds", 60.0)
            ),
        )
