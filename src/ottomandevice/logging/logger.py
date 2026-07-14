"""Backward-compatible logging facade for the core logger."""

from __future__ import annotations

from ottomandevice.core.logger import configure_logging, get_logger

__all__ = ["configure_logging", "get_logger"]
