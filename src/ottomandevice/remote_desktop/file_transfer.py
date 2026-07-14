from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ottomandevice.logging import get_logger

logger = get_logger("remote_desktop.file_transfer")

MAX_FILE_SIZE_BYTES = 104_857_600


class FileTransferError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


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

    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
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


def parse_chunk_data(value: Any) -> bytes | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None


def parse_transfer_size(value: Any, *, max_size: int) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    if value < 0 or value > max_size:
        return None
    return value


@dataclass
class UploadTransfer:
    transfer_id: str
    relative_path: str
    target_path: Path
    total_size: int
    buffer: bytearray = field(default_factory=bytearray)
    cancelled: bool = False


@dataclass
class DownloadTransfer:
    transfer_id: str
    relative_path: str
    source_path: Path
    total_size: int
    cancelled: bool = False


class FileTransferManager:
    def __init__(
        self,
        *,
        workspace_dir: Path,
        max_file_size_bytes: int = MAX_FILE_SIZE_BYTES,
        chunk_size: int = 65536,
    ) -> None:
        self._workspace_dir = workspace_dir
        self._max_file_size_bytes = max_file_size_bytes
        self._chunk_size = chunk_size
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    @property
    def max_file_size_bytes(self) -> int:
        return self._max_file_size_bytes

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    def resolve_path(self, relative_path: str) -> Path | None:
        return resolve_workspace_path(self._workspace_dir, relative_path)

    def read_file(self, path: Path) -> bytes:
        if not path.is_file():
            raise FileTransferError("NOT_FOUND", "File not found")

        size = path.stat().st_size
        if size > self._max_file_size_bytes:
            raise FileTransferError("FILE_TOO_LARGE", "File exceeds maximum size")

        return path.read_bytes()

    def write_file(self, path: Path, data: bytes) -> None:
        if len(data) > self._max_file_size_bytes:
            raise FileTransferError("FILE_TOO_LARGE", "File exceeds maximum size")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        logger.info("File uploaded to workspace: %s", path.name)

    def encode_chunk(self, data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")