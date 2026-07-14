from __future__ import annotations

import sys
from abc import ABC, abstractmethod

from ottomandevice.logging import get_logger
from ottomandevice.remote_desktop.monitor.models import MonitorInfo

logger = get_logger("remote_desktop.monitor.enumerator")


class DisplayEnumerator(ABC):
    @abstractmethod
    def enumerate(self) -> list[MonitorInfo]:
        raise NotImplementedError


def default_display_enumerator() -> DisplayEnumerator:
    if sys.platform == "win32":
        from ottomandevice.remote_desktop.monitor.platform.windows import WindowsDisplayEnumerator

        return WindowsDisplayEnumerator()
    if sys.platform == "darwin":
        from ottomandevice.remote_desktop.monitor.platform.darwin import DarwinDisplayEnumerator

        return DarwinDisplayEnumerator()
    if sys.platform.startswith("linux"):
        from ottomandevice.remote_desktop.monitor.platform.linux import LinuxDisplayEnumerator

        return LinuxDisplayEnumerator()
    return FallbackDisplayEnumerator()


class FallbackDisplayEnumerator(DisplayEnumerator):
    def enumerate(self) -> list[MonitorInfo]:
        width, height = _fallback_screen_size()
        return [
            MonitorInfo(
                id="display-1",
                number=1,
                width=width,
                height=height,
                x=0,
                y=0,
                is_primary=True,
            )
        ]


def _fallback_screen_size() -> tuple[int, int]:
    if sys.platform == "win32":
        import ctypes

        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    return 1920, 1080
