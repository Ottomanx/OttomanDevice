from __future__ import annotations

from ottomandevice.remote_desktop.monitor.enumerator import (
    DisplayEnumerator,
    FallbackDisplayEnumerator,
)
from ottomandevice.remote_desktop.monitor.models import MonitorInfo


class LinuxDisplayEnumerator(DisplayEnumerator):
    def enumerate(self) -> list[MonitorInfo]:
        try:
            return self._enumerate_xrandr()
        except Exception:
            return FallbackDisplayEnumerator().enumerate()

    def _enumerate_xrandr(self) -> list[MonitorInfo]:
        import subprocess

        from ottomandevice.remote_desktop.monitor.models import MonitorInfo

        output = subprocess.check_output(["xrandr", "--query"], text=True, timeout=2)
        monitors: list[MonitorInfo] = []
        primary_name: str | None = None
        for line in output.splitlines():
            if " connected primary " in line or line.endswith(" connected primary"):
                primary_name = line.split()[0]
            elif " connected " in line:
                pass

        for line in output.splitlines():
            if " connected " not in line:
                continue
            name = line.split()[0]
            if "primary" in line:
                primary_name = name
            geometry = line.split("+")
            if len(geometry) < 3:
                continue
            size_part = geometry[0].split()[-1]
            if "x" not in size_part:
                continue
            width_text, height_text = size_part.split("x", 1)
            x_text = geometry[1]
            y_text = geometry[2].split()[0]
            monitors.append(
                MonitorInfo(
                    id=f"linux:{name}",
                    number=len(monitors) + 1,
                    width=int(width_text),
                    height=int(height_text),
                    x=int(x_text),
                    y=int(y_text),
                    is_primary=name == primary_name,
                )
            )

        if not monitors:
            return FallbackDisplayEnumerator().enumerate()
        if not any(monitor.is_primary for monitor in monitors):
            first = monitors[0]
            monitors[0] = MonitorInfo(
                id=first.id,
                number=first.number,
                width=first.width,
                height=first.height,
                x=first.x,
                y=first.y,
                is_primary=True,
            )
        return monitors
