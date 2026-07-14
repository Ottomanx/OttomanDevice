from __future__ import annotations

import sys
from typing import Any

from ottomandevice.logging import get_logger

logger = get_logger("remote_desktop.input_injector")


class InvalidMouseEventError(Exception):
    pass


def clamp_normalized(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def parse_normalized_coordinate(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return clamp_normalized(float(value))


def parse_normalized_coordinate_strict(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    numeric = float(value)
    if numeric < 0.0 or numeric > 1.0:
        return None
    return numeric


def parse_scroll_delta(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None

    delta = int(value)
    if delta == 0:
        return None
    return delta


def extract_mouse_fields(message: dict[str, Any]) -> dict[str, Any]:
    payload = message.get("payload")
    if isinstance(payload, dict) and payload:
        return payload

    fields: dict[str, Any] = {}
    for key in ("x", "y", "button", "delta"):
        if key in message:
            fields[key] = message[key]
    return fields


class InputInjector:
    def __init__(
        self,
        *,
        screen_width: int | None = None,
        screen_height: int | None = None,
    ) -> None:
        self._screen_width = screen_width
        self._screen_height = screen_height
        self._offset_x = 0
        self._offset_y = 0

    def set_monitor_bounds(
        self,
        offset_x: int,
        offset_y: int,
        width: int,
        height: int,
    ) -> None:
        self._offset_x = offset_x
        self._offset_y = offset_y
        self._screen_width = width
        self._screen_height = height

    def _screen_size(self) -> tuple[int, int]:
        if self._screen_width is not None and self._screen_height is not None:
            return self._screen_width, self._screen_height

        if sys.platform == "win32":
            import ctypes

            user32 = ctypes.windll.user32
            return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))

        if sys.platform.startswith("linux"):
            return self._linux_screen_size()

        if sys.platform == "darwin":
            return self._macos_screen_size()

        raise InvalidMouseEventError("Screen size unavailable")

    def _linux_screen_size(self) -> tuple[int, int]:
        import ctypes

        x11 = ctypes.CDLL("libX11.so.6")
        display = x11.XOpenDisplay(None)
        if not display:
            raise InvalidMouseEventError("Screen size unavailable")

        try:
            screen = ctypes.c_int(0)
            width = int(x11.XDisplayWidth(display, screen))
            height = int(x11.XDisplayHeight(display, screen))
            return width, height
        finally:
            x11.XCloseDisplay(display)

    def _macos_screen_size(self) -> tuple[int, int]:
        import ctypes
        import ctypes.util

        app_services = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))
        main_display = app_services.CGMainDisplayID()
        width = int(app_services.CGDisplayPixelsWide(main_display))
        height = int(app_services.CGDisplayPixelsHigh(main_display))
        if width <= 0 or height <= 0:
            raise InvalidMouseEventError("Screen size unavailable")
        return width, height

    def _to_native(self, x: float, y: float) -> tuple[int, int]:
        width, height = self._screen_size()
        native_x = int(clamp_normalized(x) * max(width - 1, 0)) + self._offset_x
        native_y = int(clamp_normalized(y) * max(height - 1, 0)) + self._offset_y
        return native_x, native_y

    def move(self, x: float, y: float) -> None:
        native_x, native_y = self._to_native(x, y)
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.SetCursorPos(native_x, native_y)
            return

        if sys.platform.startswith("linux"):
            self._linux_move(native_x, native_y)
            return

        if sys.platform == "darwin":
            self._macos_move(native_x, native_y)
            return

        raise InvalidMouseEventError("Mouse move unsupported on this platform")

    def left_click(self) -> None:
        if sys.platform == "win32":
            import ctypes

            user32 = ctypes.windll.user32
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            return

        if sys.platform.startswith("linux"):
            self._linux_button(1)
            return

        if sys.platform == "darwin":
            self._macos_click(button=0)
            return

        raise InvalidMouseEventError("Mouse click unsupported on this platform")

    def right_click(self) -> None:
        if sys.platform == "win32":
            import ctypes

            user32 = ctypes.windll.user32
            user32.mouse_event(0x0008, 0, 0, 0, 0)
            user32.mouse_event(0x0010, 0, 0, 0, 0)
            return

        if sys.platform.startswith("linux"):
            self._linux_button(3)
            return

        if sys.platform == "darwin":
            self._macos_click(button=1)
            return

        raise InvalidMouseEventError("Mouse click unsupported on this platform")

    def double_click(self) -> None:
        if sys.platform == "win32":
            import ctypes

            user32 = ctypes.windll.user32
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            user32.mouse_event(0x0002, 0, 0, 0, 0)
            user32.mouse_event(0x0004, 0, 0, 0, 0)
            return

        if sys.platform.startswith("linux"):
            self._linux_button(1)
            self._linux_button(1)
            return

        if sys.platform == "darwin":
            self._macos_click(button=0)
            self._macos_click(button=0)
            return

        raise InvalidMouseEventError("Mouse double click unsupported on this platform")

    def scroll(self, delta: int) -> None:
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.mouse_event(0x0800, 0, 0, int(delta), 0)
            return

        if sys.platform.startswith("linux"):
            self._linux_scroll(delta)
            return

        if sys.platform == "darwin":
            self._macos_scroll(delta)
            return

        raise InvalidMouseEventError("Mouse scroll unsupported on this platform")

    def click(self, button: str) -> None:
        if button == "left":
            self.left_click()
            return
        if button == "right":
            self.right_click()
            return
        raise InvalidMouseEventError("Invalid mouse button")

    def _linux_move(self, native_x: int, native_y: int) -> None:
        import ctypes

        xtest = ctypes.CDLL("libXtst.so.6")
        x11 = ctypes.CDLL("libX11.so.6")
        display = x11.XOpenDisplay(None)
        if not display:
            raise InvalidMouseEventError("Mouse move unsupported on this platform")

        try:
            xtest.XTestFakeMotionEvent(display, 0, native_x, native_y, 0)
            x11.XFlush(display)
        finally:
            x11.XCloseDisplay(display)

    def _linux_button(self, button: int) -> None:
        import ctypes

        xtest = ctypes.CDLL("libXtst.so.6")
        x11 = ctypes.CDLL("libX11.so.6")
        display = x11.XOpenDisplay(None)
        if not display:
            raise InvalidMouseEventError("Mouse click unsupported on this platform")

        try:
            xtest.XTestFakeButtonEvent(display, button, True, 0)
            xtest.XTestFakeButtonEvent(display, button, False, 0)
            x11.XFlush(display)
        finally:
            x11.XCloseDisplay(display)

    def _linux_scroll(self, delta: int) -> None:
        button = 4 if delta > 0 else 5
        clicks = max(1, abs(delta) // 120)
        for _ in range(clicks):
            self._linux_button(button)

    def _macos_move(self, native_x: int, native_y: int) -> None:
        import ctypes
        import ctypes.util

        app_services = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))
        move_type = 5
        event = app_services.CGEventCreateMouseEvent(None, move_type, (native_x, native_y), 0)
        if not event:
            raise InvalidMouseEventError("Mouse move unsupported on this platform")
        app_services.CGEventPost(0, event)

    def _macos_click(self, *, button: int) -> None:
        import ctypes
        import ctypes.util

        app_services = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))
        down_type = 1 if button == 0 else 3
        up_type = 2 if button == 0 else 4
        point = app_services.CGEventGetLocation(
            app_services.CGEventCreate(None),
        )
        down_event = app_services.CGEventCreateMouseEvent(None, down_type, point, button)
        up_event = app_services.CGEventCreateMouseEvent(None, up_type, point, button)
        app_services.CGEventPost(0, down_event)
        app_services.CGEventPost(0, up_event)

    def _macos_scroll(self, delta: int) -> None:
        import ctypes
        import ctypes.util

        app_services = ctypes.CDLL(ctypes.util.find_library("ApplicationServices"))
        scroll_event = app_services.CGEventCreateScrollWheelEvent(
            None,
            0,
            1,
            float(delta) / 120.0,
        )
        app_services.CGEventPost(0, scroll_event)
