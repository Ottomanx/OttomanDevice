from __future__ import annotations

import ctypes
import ctypes.util

from ottomandevice.remote_desktop.monitor.enumerator import (
    DisplayEnumerator,
    FallbackDisplayEnumerator,
)
from ottomandevice.remote_desktop.monitor.models import MonitorInfo


class DarwinDisplayEnumerator(DisplayEnumerator):
    def enumerate(self) -> list[MonitorInfo]:
        try:
            app_services = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))
            max_displays = 32
            display_ids = (ctypes.c_uint32 * max_displays)()
            display_count = ctypes.c_uint32(0)
            result = app_services.CGGetActiveDisplayList(
                max_displays,
                display_ids,
                ctypes.byref(display_count),
            )
            if result != 0 or display_count.value == 0:
                return FallbackDisplayEnumerator().enumerate()

            main_display = app_services.CGMainDisplayID()
            monitors: list[MonitorInfo] = []
            for index in range(int(display_count.value)):
                display_id = int(display_ids[index])
                width = int(app_services.CGDisplayPixelsWide(display_id))
                height = int(app_services.CGDisplayPixelsHigh(display_id))
                monitors.append(
                    MonitorInfo(
                        id=f"darwin:{display_id}",
                        number=index + 1,
                        width=max(width, 1),
                        height=max(height, 1),
                        x=0,
                        y=0,
                        is_primary=display_id == main_display,
                    )
                )
            return monitors
        except Exception:
            return FallbackDisplayEnumerator().enumerate()
