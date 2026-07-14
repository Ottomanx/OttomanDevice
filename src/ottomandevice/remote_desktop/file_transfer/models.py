from __future__ import annotations

from enum import Enum
from pathlib import Path


class TransferState(str, Enum):
    IDLE = "idle"
    INITIATED = "initiated"
    QUEUED = "queued"
    ACTIVE = "active"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETE = "complete"
    CANCELLED = "cancelled"
    FAILED = "failed"
    RETRYING = "retrying"


class TransferDirection(str, Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"


class UploadSession:
    __slots__ = (
        "transfer_id",
        "relative_path",
        "target_path",
        "partial_path",
        "total_size",
        "transferred",
        "sha256_expected",
        "state",
        "cancelled",
        "paused",
        "overwrite",
    )

    def __init__(
        self,
        *,
        transfer_id: str,
        relative_path: str,
        target_path: Path,
        partial_path: Path,
        total_size: int,
        transferred: int = 0,
        sha256_expected: str | None = None,
        state: TransferState = TransferState.ACTIVE,
        cancelled: bool = False,
        paused: bool = False,
        overwrite: bool = False,
    ) -> None:
        self.transfer_id = transfer_id
        self.relative_path = relative_path
        self.target_path = target_path
        self.partial_path = partial_path
        self.total_size = total_size
        self.transferred = transferred
        self.sha256_expected = sha256_expected
        self.state = state
        self.cancelled = cancelled
        self.paused = paused
        self.overwrite = overwrite


class DownloadSession:
    __slots__ = (
        "transfer_id",
        "relative_path",
        "source_path",
        "total_size",
        "offset",
        "sha256",
        "state",
        "cancelled",
        "paused",
    )

    def __init__(
        self,
        *,
        transfer_id: str,
        relative_path: str,
        source_path: Path,
        total_size: int,
        offset: int = 0,
        sha256: str | None = None,
        state: TransferState = TransferState.QUEUED,
        cancelled: bool = False,
        paused: bool = False,
    ) -> None:
        self.transfer_id = transfer_id
        self.relative_path = relative_path
        self.source_path = source_path
        self.total_size = total_size
        self.offset = offset
        self.sha256 = sha256
        self.state = state
        self.cancelled = cancelled
        self.paused = paused
