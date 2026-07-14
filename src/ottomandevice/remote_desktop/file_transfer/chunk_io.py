from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass
class TransferManifest:
    transfer_id: str
    direction: str
    relative_path: str
    total_size: int
    transferred: int
    sha256: str | None = None
    partial_path: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransferManifest | None:
        transfer_id = data.get("transfer_id")
        direction = data.get("direction")
        relative_path = data.get("relative_path")
        total_size = data.get("total_size")
        transferred = data.get("transferred")
        if (
            not isinstance(transfer_id, str)
            or not isinstance(direction, str)
            or not isinstance(relative_path, str)
            or not isinstance(total_size, int)
            or not isinstance(transferred, int)
        ):
            return None
        sha256 = data.get("sha256")
        partial_path = data.get("partial_path")
        return cls(
            transfer_id=transfer_id,
            direction=direction,
            relative_path=relative_path,
            total_size=total_size,
            transferred=transferred,
            sha256=sha256 if isinstance(sha256, str) else None,
            partial_path=partial_path if isinstance(partial_path, str) else None,
        )


class TransferManifestStore:
    def __init__(self, manifest_dir: Path, partial_dir: Path) -> None:
        self._manifest_dir = manifest_dir
        self._partial_dir = partial_dir

    def _ensure_dirs(self) -> None:
        self._manifest_dir.mkdir(parents=True, exist_ok=True)
        self._partial_dir.mkdir(parents=True, exist_ok=True)

    @property
    def partial_dir(self) -> Path:
        return self._partial_dir

    def partial_path_for(self, transfer_id: str) -> Path:
        self._ensure_dirs()
        return self._partial_dir / f"{transfer_id}.part"

    def _manifest_path(self, transfer_id: str) -> Path:
        return self._manifest_dir / f"{transfer_id}.json"

    def save(self, manifest: TransferManifest) -> None:
        self._ensure_dirs()
        path = self._manifest_path(manifest.transfer_id)
        path.write_text(json.dumps(asdict(manifest)), encoding="utf-8")

    def load(self, transfer_id: str) -> TransferManifest | None:
        path = self._manifest_path(transfer_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        return TransferManifest.from_dict(data)

    def delete(self, transfer_id: str) -> None:
        manifest_path = self._manifest_path(transfer_id)
        if manifest_path.is_file():
            manifest_path.unlink()
        partial_path = self.partial_path_for(transfer_id)
        if partial_path.is_file():
            partial_path.unlink()


def write_chunk_at_offset(
    path: Path,
    offset: int,
    data: bytes,
    *,
    fsync_interval_bytes: int,
    bytes_since_fsync: int,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("r+b" if path.exists() else "wb") as handle:
        handle.seek(offset)
        handle.write(data)
        new_bytes_since_fsync = bytes_since_fsync + len(data)
        if new_bytes_since_fsync >= fsync_interval_bytes:
            handle.flush()
            os.fsync(handle.fileno())
            return 0
        return new_bytes_since_fsync


def read_chunk_at_offset(path: Path, offset: int, size: int) -> bytes:
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read(size)


def truncate_partial(path: Path, size: int) -> None:
    if not path.exists():
        return
    with path.open("r+b") as handle:
        handle.truncate(size)


def finalize_partial(partial_path: Path, target_path: Path) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if target_path.exists():
        target_path.unlink()
    partial_path.replace(target_path)
