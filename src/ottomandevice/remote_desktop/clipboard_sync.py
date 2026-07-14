from __future__ import annotations

import sys
from typing import Any

from ottomandevice.logging import get_logger

logger = get_logger("remote_desktop.clipboard_sync")

MAX_CLIPBOARD_TEXT_LENGTH = 262_144
CF_UNICODETEXT = 13


def parse_clipboard_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if len(value) > MAX_CLIPBOARD_TEXT_LENGTH:
        return None
    if "\x00" in value:
        return None
    return value


class ClipboardManager:
    def read(self) -> str:
        if sys.platform != "win32":
            raise OSError("Clipboard read unsupported on this platform")

        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.OpenClipboard(0):
            logger.warning("Failed to open clipboard for read")
            return ""

        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""

            data = kernel32.GlobalLock(handle)
            if not data:
                return ""

            try:
                return ctypes.wstring_at(data)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def write(self, text: str) -> None:
        if sys.platform != "win32":
            raise OSError("Clipboard write unsupported on this platform")

        import ctypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        if not user32.OpenClipboard(0):
            raise OSError("Failed to open clipboard for write")

        GMEM_MOVEABLE = 0x0002
        try:
            user32.EmptyClipboard()
            encoded = text.encode("utf-16-le") + b"\x00\x00"
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
            if not handle:
                raise OSError("Failed to allocate clipboard memory")

            locked = kernel32.GlobalLock(handle)
            if not locked:
                kernel32.GlobalFree(handle)
                raise OSError("Failed to lock clipboard memory")

            try:
                ctypes.memmove(locked, encoded, len(encoded))
            finally:
                kernel32.GlobalUnlock(handle)

            if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                kernel32.GlobalFree(handle)
                raise OSError("Failed to set clipboard data")
        finally:
            user32.CloseClipboard()