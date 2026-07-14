from __future__ import annotations

from pathlib import Path
from typing import Any


def validate_relative_path(path: Any) -> str | None:
    if not isinstance(path, str):
        return None

    normalized = path.strip().replace("\\", "/")
    if not normalized or normalized in {".", ".."}:
        return None
    if normalized.startswith("/"):
        return None
    if ":" in normalized:
        return None
    if "\x00" in normalized:
        return None

    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    if any(len(part) > 255 for part in parts):
        return None

    return normalized


def resolve_workspace_path(workspace: Path, relative_path: str) -> Path | None:
    validated = validate_relative_path(relative_path)
    if validated is None:
        return None

    base = workspace.resolve()
    target = (base / validated).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None

    return target


def parse_transfer_size(value: Any, *, max_size: int) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if value < 0 or value > max_size:
        return None
    return value


def parse_sha256(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"", "pending"}:
        return None
    if len(normalized) != 64:
        return None
    if not all(char in "0123456789abcdef" for char in normalized):
        return None
    return normalized
