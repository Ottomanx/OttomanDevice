from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from ottomandevice.runtime import PROJECT_ROOT

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "ottomandevice.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

_configured = False


def _configure_logging() -> None:
    global _configured
    if _configured:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger("ottomandevice")
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.propagate = False

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_logging()
    return logging.getLogger(f"ottomandevice.{name}")
