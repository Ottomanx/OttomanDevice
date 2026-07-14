from __future__ import annotations

import ctypes
from ctypes import wintypes

from ottomandevice.remote_desktop.monitor.enumerator import DisplayEnumerator
from ottomandevice.remote_desktop.monitor.models import MonitorInfo


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


MONITORINFOF_PRIMARY = 1


class WindowsDisplayEnumerator(DisplayEnumerator):
    def enumerate(self) -> list[MonitorInfo]:
        user32 = ctypes.windll.user32
        collected: list[MonitorInfo] = []

        def callback(hmonitor: int, _hdc: int, _rect: int, _data: int) -> int:
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if not user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                return 1

            rect = info.rcMonitor
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            device_name = info.szDevice.strip() or f"monitor-{len(collected) + 1}"
            monitor_id = f"win:{device_name}"
            collected.append(
                MonitorInfo(
                    id=monitor_id,
                    number=len(collected) + 1,
                    width=max(width, 1),
                    height=max(height, 1),
                    x=int(rect.left),
                    y=int(rect.top),
                    is_primary=bool(info.dwFlags & MONITORINFOF_PRIMARY),
                )
            )
            return 1

        enum_proc = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.POINTER(wintypes.RECT),
            ctypes.c_double,
        )(callback)
        user32.EnumDisplayMonitors(None, None, enum_proc, 0)

        if not collected:
            from ottomandevice.remote_desktop.monitor.enumerator import FallbackDisplayEnumerator

            return FallbackDisplayEnumerator().enumerate()

        primary = [monitor for monitor in collected if monitor.is_primary]
        if not primary:
            first = collected[0]
            collected[0] = MonitorInfo(
                id=first.id,
                number=first.number,
                width=first.width,
                height=first.height,
                x=first.x,
                y=first.y,
                is_primary=True,
            )
        return collected
