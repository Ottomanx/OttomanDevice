from __future__ import annotations

from enum import Enum
from typing import Any, Iterable


class Permission(str, Enum):
    DESKTOP = "desktop"
    MOUSE = "mouse"
    KEYBOARD = "keyboard"
    CLIPBOARD = "clipboard"
    FILE_TRANSFER = "file_transfer"
    OTA = "ota"
    RESTART = "restart"
    CAMERA = "camera"
    MICROPHONE = "microphone"


ALL_PERMISSIONS: frozenset[str] = frozenset(permission.value for permission in Permission)


def normalize_permissions(values: Iterable[Any] | None) -> frozenset[str]:
    if values is None:
        return frozenset()

    normalized: set[str] = set()
    for value in values:
        if isinstance(value, str) and value in ALL_PERMISSIONS:
            normalized.add(value)
    return frozenset(normalized)


def has_permission(permissions: Iterable[str], permission: Permission | str) -> bool:
    required = permission.value if isinstance(permission, Permission) else permission
    return required in frozenset(permissions)


__all__ = [
    "ALL_PERMISSIONS",
    "Permission",
    "has_permission",
    "normalize_permissions",
]