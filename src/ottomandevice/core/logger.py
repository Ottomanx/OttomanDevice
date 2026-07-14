from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from ottomandevice.paths import PROJECT_ROOT

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
DEFAULT_LOG_LEVEL = "INFO"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5

_configured = False


@dataclass(frozen=True)
class LogConfig:
    """Runtime logging configuration."""

    log_dir: Path
    level: int
    max_bytes: int
    backup_count: int


def _resolve_log_config() -> LogConfig:
    log_root = PROJECT_ROOT / os.getenv("OTTOMAN_LOG_DIR", "logs")
    level_name = os.getenv("OTTOMAN_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)
    max_bytes = int(os.getenv("OTTOMAN_LOG_MAX_BYTES", str(DEFAULT_MAX_BYTES)))
    backup_count = int(os.getenv("OTTOMAN_LOG_BACKUP_COUNT", str(DEFAULT_BACKUP_COUNT)))
    return LogConfig(
        log_dir=log_root,
        level=level,
        max_bytes=max_bytes,
        backup_count=backup_count,
    )


def _daily_log_dir(base_dir: Path) -> Path:
    day_folder = datetime.now().strftime("%Y-%m-%d")
    return base_dir / day_folder


def configure_logging(*, force: bool = False) -> None:
    """Configure process-wide logging handlers.

    Args:
        force: Reconfigure even if logging was already configured.
    """
    global _configured
    if _configured and not force:
        return

    config = _resolve_log_config()
    daily_dir = _daily_log_dir(config.log_dir)
    daily_dir.mkdir(parents=True, exist_ok=True)
    log_file = daily_dir / "ottomandevice.log"

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger("ottomandevice")
    root_logger.handlers.clear()
    root_logger.setLevel(config.level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.propagate = False

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under the ``ottomandevice`` root.

    Args:
        name: Logical logger name, typically a module or service name.

    Returns:
        Configured ``logging.Logger`` instance.
    """
    configure_logging()
    return logging.getLogger(f"ottomandevice.{name}")
