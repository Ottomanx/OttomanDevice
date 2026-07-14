from __future__ import annotations

import sys

from ottomandevice.paths import PROJECT_ROOT


def _ensure_project_root_on_path() -> None:
    root = str(PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


_ensure_project_root_on_path()

from device import Device, get_device_id, load_or_create_device_id, register_device  # noqa: E402

__all__ = [
    "PROJECT_ROOT",
    "Device",
    "get_device_id",
    "load_or_create_device_id",
    "register_device",
]
