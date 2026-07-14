from __future__ import annotations

import sys
from typing import Any

from ottomandevice.logging import get_logger

logger = get_logger("remote_desktop.keyboard_injector")

FORBIDDEN_KEYS = frozenset({"Meta", "Control", "Alt", "OS"})

KEY_CODE_TO_VK: dict[str, int] = {
    **{f"Key{chr(ord('A') + index)}": 0x41 + index for index in range(26)},
    **{f"Digit{index}": 0x30 + index for index in range(10)},
    "Enter": 0x0D,
    "Backspace": 0x08,
    "Tab": 0x09,
    "Escape": 0x1B,
    "Space": 0x20,
    "ArrowLeft": 0x25,
    "ArrowUp": 0x26,
    "ArrowRight": 0x27,
    "ArrowDown": 0x28,
    "Home": 0x24,
    "End": 0x23,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "Delete": 0x2E,
    **{f"F{index}": 0x70 + index - 1 for index in range(1, 13)},
}

MAX_TEXT_INPUT_LENGTH = 128

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
INPUT_KEYBOARD = 1


class InvalidKeyboardEventError(Exception):
    pass


def _is_forbidden_key(key: str) -> bool:
    return any(key.startswith(prefix) for prefix in FORBIDDEN_KEYS)


def parse_key(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if _is_forbidden_key(value):
        return None
    if value not in KEY_CODE_TO_VK:
        return None
    return value


def parse_text_input(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if len(value) > MAX_TEXT_INPUT_LENGTH:
        return None
    for char in value:
        if ord(char) < 32 and char not in "\t\n":
            return None
    return value


class KeyboardInjector:
    def key_down(self, key: Any) -> None:
        parsed = parse_key(key)
        if parsed is None:
            raise InvalidKeyboardEventError("Invalid keyboard key")

        vk = KEY_CODE_TO_VK[parsed]
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            return

        raise InvalidKeyboardEventError("Keyboard input unsupported on this platform")

    def key_up(self, key: Any) -> None:
        parsed = parse_key(key)
        if parsed is None:
            raise InvalidKeyboardEventError("Invalid keyboard key")

        vk = KEY_CODE_TO_VK[parsed]
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
            return

        raise InvalidKeyboardEventError("Keyboard input unsupported on this platform")

    def text_input(self, text: Any) -> None:
        parsed = parse_text_input(text)
        if parsed is None:
            raise InvalidKeyboardEventError("Invalid text input")

        if not parsed:
            return

        if sys.platform != "win32":
            raise InvalidKeyboardEventError("Keyboard input unsupported on this platform")

        import ctypes
        from ctypes import wintypes

        ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = (
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR),
            )

        class INPUT(ctypes.Structure):
            class _INPUT_UNION(ctypes.Union):
                _fields_ = (("ki", KEYBDINPUT),)

            _anonymous_ = ("_input",)
            _fields_ = (
                ("type", wintypes.DWORD),
                ("_input", _INPUT_UNION),
            )

        user32 = ctypes.windll.user32
        inputs: list[INPUT] = []

        for char in parsed:
            code_point = ord(char)
            inputs.append(
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(
                        wVk=0,
                        wScan=code_point,
                        dwFlags=KEYEVENTF_UNICODE,
                        time=0,
                        dwExtraInfo=0,
                    ),
                )
            )
            inputs.append(
                INPUT(
                    type=INPUT_KEYBOARD,
                    ki=KEYBDINPUT(
                        wVk=0,
                        wScan=code_point,
                        dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                        time=0,
                        dwExtraInfo=0,
                    ),
                )
            )

        array_type = INPUT * len(inputs)
        sent = user32.SendInput(len(inputs), array_type(*inputs), ctypes.sizeof(INPUT))
        if sent != len(inputs):
            logger.warning("SendInput sent %s of %s unicode events", sent, len(inputs))
            raise InvalidKeyboardEventError("Failed to inject text input")