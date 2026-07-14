from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from ottomandevice.logging import get_logger
from ottomandevice.remote_desktop.file_transfer.bandwidth import (
    BandwidthLimiter,
    NoOpBandwidthLimiter,
)
from ottomandevice.remote_desktop.file_transfer.chunk_io import (
    TransferManifest,
    TransferManifestStore,
    finalize_partial,
    read_chunk_at_offset,
    write_chunk_at_offset,
)
from ottomandevice.remote_desktop.file_transfer.chunk_size import (
    ChunkSizeStrategy,
    FixedChunkSizeStrategy,
)
from ottomandevice.remote_desktop.file_transfer.errors import FileTransferError
from ottomandevice.remote_desktop.file_transfer.models import (
    DownloadSession,
    TransferState,
    UploadSession,
)
from ottomandevice.remote_desktop.file_transfer.path_validator import (
    parse_sha256,
    parse_transfer_size,
    resolve_workspace_path,
    validate_relative_path,
)
from ottomandevice.remote_desktop.file_transfer.queue import TransferWorkerPool
from ottomandevice.remote_desktop.file_transfer.sha256_stream import (
    Sha256Stream,
    file_sha256,
)

logger = get_logger("remote_desktop.file_transfer")

ProgressCallback = Callable[[str, int, int, str], Awaitable[None]]
ChunkCallback = Callable[[str, bytes, int, bool], Awaitable[None]]
CompleteCallback = Callable[[str, str, int, str | None], Awaitable[None]]
ErrorCallback = Callable[[str, str, str], Awaitable[None]]


class TransferManager:
    """Orchestrates file transfers using raw bytes. Wire encoding is external."""

    def __init__(
        self,
        *,
        workspace_dir: Path,
        max_file_size_bytes: int,
        chunk_size: int | None = None,
        chunk_size_strategy: ChunkSizeStrategy | None = None,
        manifest_dir: Path | None = None,
        partial_dir: Path | None = None,
        fsync_interval_bytes: int = 4_194_304,
        allow_overwrite: bool = False,
        worker_pool: TransferWorkerPool | None = None,
        bandwidth_limiter: BandwidthLimiter | None = None,
    ) -> None:
        self._workspace_dir = workspace_dir
        self._max_file_size_bytes = max_file_size_bytes
        if chunk_size_strategy is None:
            chunk_size_strategy = FixedChunkSizeStrategy(chunk_size or 65536)
        self._chunk_size_strategy = chunk_size_strategy
        self._fsync_interval_bytes = fsync_interval_bytes
        self._allow_overwrite = allow_overwrite
        self._worker_pool = worker_pool or TransferWorkerPool(max_workers=2)
        self._bandwidth_limiter = bandwidth_limiter or NoOpBandwidthLimiter()
        self._workspace_dir.mkdir(parents=True, exist_ok=True)

        partial = partial_dir or workspace_dir / ".partials"
        manifest = manifest_dir or workspace_dir / ".manifests"
        self._manifest_store = TransferManifestStore(manifest, partial)

        self._uploads: dict[str, UploadSession] = {}
        self._upload_hashers: dict[str, Sha256Stream] = {}
        self._upload_fsync_counters: dict[str, int] = {}
        self._downloads: dict[str, DownloadSession] = {}

    @property
    def workspace_dir(self) -> Path:
        return self._workspace_dir

    @property
    def max_file_size_bytes(self) -> int:
        return self._max_file_size_bytes

    @property
    def chunk_size(self) -> int:
        return self._chunk_size_strategy.chunk_size()

    @property
    def chunk_size_strategy(self) -> ChunkSizeStrategy:
        return self._chunk_size_strategy

    @property
    def worker_pool(self) -> TransferWorkerPool:
        return self._worker_pool

    @property
    def bandwidth_limiter(self) -> BandwidthLimiter:
        return self._bandwidth_limiter

    def resolve_path(self, relative_path: str) -> Path | None:
        return resolve_workspace_path(self._workspace_dir, relative_path)

    def get_upload(self, transfer_id: str) -> UploadSession | None:
        return self._uploads.get(transfer_id)

    def get_download(self, transfer_id: str) -> DownloadSession | None:
        return self._downloads.get(transfer_id)

    async def initiate_upload(
        self,
        *,
        transfer_id: str,
        relative_path: str,
        total_size: int,
        sha256: str | None = None,
        offset: int = 0,
        resume: bool = False,
        overwrite: bool = False,
    ) -> UploadSession:
        if transfer_id in self._uploads:
            raise FileTransferError("INVALID_TRANSFER", "Transfer already active")

        validated_path = validate_relative_path(relative_path)
        if validated_path is None:
            raise FileTransferError("INVALID_PATH", "Invalid file path")

        parsed_size = parse_transfer_size(total_size, max_size=self._max_file_size_bytes)
        if parsed_size is None:
            raise FileTransferError("FILE_TOO_LARGE", "Invalid file size")

        target = self.resolve_path(validated_path)
        if target is None:
            raise FileTransferError("INVALID_PATH", "Invalid file path")

        if target.exists() and not overwrite and not self._allow_overwrite:
            raise FileTransferError("OVERWRITE_DENIED", "File already exists")

        partial_path = self._manifest_store.partial_path_for(transfer_id)
        transferred = 0
        hasher = Sha256Stream()

        if resume:
            manifest = self._manifest_store.load(transfer_id)
            if manifest is None or not partial_path.is_file():
                raise FileTransferError("RESUME_UNAVAILABLE", "Resume data unavailable")
            if (
                manifest.relative_path != validated_path
                or manifest.total_size != parsed_size
                or manifest.direction != "upload"
            ):
                raise FileTransferError("RESUME_UNAVAILABLE", "Resume metadata mismatch")
            transferred = manifest.transferred
            if offset > 0 and offset != transferred:
                raise FileTransferError("RESUME_UNAVAILABLE", "Invalid resume offset")
            if sha256 and manifest.sha256 and sha256 != manifest.sha256:
                raise FileTransferError("RESUME_UNAVAILABLE", "SHA256 mismatch")
        elif partial_path.is_file():
            partial_path.unlink()

        expected_sha256 = parse_sha256(sha256)

        session = UploadSession(
            transfer_id=transfer_id,
            relative_path=validated_path,
            target_path=target,
            partial_path=partial_path,
            total_size=parsed_size,
            transferred=transferred,
            sha256_expected=expected_sha256,
            state=TransferState.ACTIVE,
            overwrite=overwrite or self._allow_overwrite,
        )
        self._uploads[transfer_id] = session
        self._upload_hashers[transfer_id] = hasher
        self._upload_fsync_counters[transfer_id] = 0

        if resume and transferred > 0:
            existing = await asyncio.to_thread(
                read_chunk_at_offset,
                partial_path,
                0,
                transferred,
            )
            hasher.update(existing)

        self._persist_upload_manifest(session)
        return session

    async def handle_upload_chunk(
        self,
        transfer_id: str,
        data: bytes,
        *,
        offset: int | None = None,
    ) -> tuple[int, int, bool]:
        session = self._uploads.get(transfer_id)
        if session is None or session.cancelled:
            raise FileTransferError("INVALID_TRANSFER", "Transfer not active")
        if session.paused:
            raise FileTransferError("PAUSED", "Transfer paused")

        expected_offset = session.transferred if offset is None else offset
        if expected_offset != session.transferred:
            raise FileTransferError("INVALID_CHUNK", "Unexpected chunk offset")
        if expected_offset + len(data) > session.total_size:
            raise FileTransferError("FILE_TOO_LARGE", "Upload exceeds declared size")

        await self._bandwidth_limiter.acquire(len(data))

        bytes_since_fsync = self._upload_fsync_counters.get(transfer_id, 0)
        new_fsync_counter = await asyncio.to_thread(
            write_chunk_at_offset,
            session.partial_path,
            expected_offset,
            data,
            fsync_interval_bytes=self._fsync_interval_bytes,
            bytes_since_fsync=bytes_since_fsync,
        )
        self._upload_fsync_counters[transfer_id] = new_fsync_counter

        hasher = self._upload_hashers[transfer_id]
        hasher.update(data)
        session.transferred += len(data)
        await self._bandwidth_limiter.report(len(data))
        self._persist_upload_manifest(session)

        complete = session.transferred >= session.total_size
        return session.transferred, session.total_size, complete

    async def finalize_upload(self, transfer_id: str) -> tuple[str, int, str | None]:
        session = self._uploads.pop(transfer_id, None)
        hasher = self._upload_hashers.pop(transfer_id, None)
        self._upload_fsync_counters.pop(transfer_id, None)
        if session is None or hasher is None:
            raise FileTransferError("INVALID_TRANSFER", "Transfer not active")
        if session.cancelled:
            raise FileTransferError("CANCELLED", "Transfer cancelled")
        if session.transferred != session.total_size:
            raise FileTransferError("INVALID_CHUNK", "Upload incomplete")

        session.state = TransferState.VERIFYING
        digest = hasher.hexdigest()
        if session.sha256_expected and digest != session.sha256_expected:
            await self._cleanup_upload(session)
            raise FileTransferError("HASH_MISMATCH", "SHA256 verification failed")

        await asyncio.to_thread(
            finalize_partial,
            session.partial_path,
            session.target_path,
        )
        self._manifest_store.delete(transfer_id)
        session.state = TransferState.COMPLETE
        logger.info("File uploaded to workspace: %s", session.relative_path)
        return session.relative_path, session.total_size, digest

    async def pause_upload(self, transfer_id: str) -> None:
        session = self._uploads.get(transfer_id)
        if session is None:
            raise FileTransferError("INVALID_TRANSFER", "Transfer not active")
        session.paused = True
        session.state = TransferState.PAUSED

    async def resume_upload(self, transfer_id: str) -> UploadSession:
        session = self._uploads.get(transfer_id)
        if session is None:
            manifest = self._manifest_store.load(transfer_id)
            if manifest is None:
                raise FileTransferError("RESUME_UNAVAILABLE", "Resume data unavailable")
            return await self.initiate_upload(
                transfer_id=transfer_id,
                relative_path=manifest.relative_path,
                total_size=manifest.total_size,
                sha256=manifest.sha256,
                offset=manifest.transferred,
                resume=True,
            )
        session.paused = False
        session.state = TransferState.ACTIVE
        return session

    async def cancel_upload(self, transfer_id: str) -> None:
        session = self._uploads.pop(transfer_id, None)
        self._upload_hashers.pop(transfer_id, None)
        self._upload_fsync_counters.pop(transfer_id, None)
        if session is not None:
            session.cancelled = True
            await self._cleanup_upload(session)

    async def initiate_download(
        self,
        *,
        transfer_id: str,
        relative_path: str,
        offset: int = 0,
        resume: bool = False,
    ) -> DownloadSession:
        if transfer_id in self._downloads:
            raise FileTransferError("INVALID_TRANSFER", "Transfer already active")

        validated_path = validate_relative_path(relative_path)
        if validated_path is None:
            raise FileTransferError("INVALID_PATH", "Invalid file path")

        target = self.resolve_path(validated_path)
        if target is None or not target.is_file():
            raise FileTransferError("NOT_FOUND", "File not found")

        try:
            size = target.stat().st_size
        except OSError as exc:
            raise FileTransferError("NOT_FOUND", "File not found") from exc

        if size > self._max_file_size_bytes:
            raise FileTransferError("FILE_TOO_LARGE", "File exceeds maximum size")

        start_offset = offset
        if resume and start_offset > size:
            raise FileTransferError("RESUME_UNAVAILABLE", "Invalid resume offset")

        digest = await asyncio.to_thread(file_sha256, target)

        session = DownloadSession(
            transfer_id=transfer_id,
            relative_path=validated_path,
            source_path=target,
            total_size=size,
            offset=start_offset,
            sha256=digest,
            state=TransferState.QUEUED,
        )
        self._downloads[transfer_id] = session
        return session

    async def queue_download(
        self,
        session: DownloadSession,
        *,
        on_chunk: ChunkCallback,
        on_progress: ProgressCallback,
        on_complete: CompleteCallback,
        on_error: ErrorCallback,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        async def run_download() -> None:
            session.state = TransferState.ACTIVE
            try:
                await self._run_download_stream(
                    session,
                    on_chunk=on_chunk,
                    on_progress=on_progress,
                    on_complete=on_complete,
                    should_continue=should_continue,
                )
            except FileTransferError as exc:
                await on_error(session.transfer_id, exc.code, exc.message)
            except asyncio.CancelledError:
                await on_error(session.transfer_id, "CANCELLED", "Transfer cancelled")
            except Exception:
                logger.info("File download failed")
                await on_error(session.transfer_id, "INTERNAL_ERROR", "Download failed")
            finally:
                self._downloads.pop(session.transfer_id, None)

        await self._worker_pool.submit(session.transfer_id, run_download)

    async def _run_download_stream(
        self,
        session: DownloadSession,
        *,
        on_chunk: ChunkCallback,
        on_progress: ProgressCallback,
        on_complete: CompleteCallback,
        should_continue: Callable[[], bool] | None = None,
    ) -> None:
        offset = session.offset
        total = session.total_size
        chunk_size = self._chunk_size_strategy.chunk_size()

        while offset < total:
            if session.cancelled:
                raise FileTransferError("CANCELLED", "Transfer cancelled")
            if session.paused:
                raise FileTransferError("PAUSED", "Transfer paused")
            if should_continue is not None and not should_continue():
                raise FileTransferError("CANCELLED", "Transfer cancelled")

            read_size = min(chunk_size, total - offset)
            started = time.monotonic()
            chunk = await asyncio.to_thread(
                read_chunk_at_offset,
                session.source_path,
                offset,
                read_size,
            )
            await self._bandwidth_limiter.acquire(len(chunk))

            final = offset + len(chunk) >= total
            await on_chunk(session.transfer_id, chunk, offset, final)
            offset += len(chunk)
            session.offset = offset

            elapsed_ms = (time.monotonic() - started) * 1000.0
            self._chunk_size_strategy.on_chunk_sent(len(chunk), elapsed_ms)
            await self._bandwidth_limiter.report(len(chunk))
            await on_progress(session.transfer_id, offset, total, "download")
            await asyncio.sleep(0)

        await on_complete(
            session.transfer_id,
            session.relative_path,
            total,
            session.sha256,
        )

    async def pause_download(self, transfer_id: str) -> None:
        session = self._downloads.get(transfer_id)
        if session is None:
            raise FileTransferError("INVALID_TRANSFER", "Transfer not active")
        session.paused = True
        session.state = TransferState.PAUSED

    async def resume_download(self, transfer_id: str) -> None:
        session = self._downloads.get(transfer_id)
        if session is None:
            raise FileTransferError("RESUME_UNAVAILABLE", "Transfer not active")
        session.paused = False
        session.state = TransferState.ACTIVE

    async def cancel_download(self, transfer_id: str) -> None:
        session = self._downloads.get(transfer_id)
        if session is not None:
            session.cancelled = True
        await self._worker_pool.cancel_pending(transfer_id)

    def _persist_upload_manifest(self, session: UploadSession) -> None:
        self._manifest_store.save(
            TransferManifest(
                transfer_id=session.transfer_id,
                direction="upload",
                relative_path=session.relative_path,
                total_size=session.total_size,
                transferred=session.transferred,
                sha256=session.sha256_expected,
                partial_path=str(session.partial_path),
            )
        )

    async def _cleanup_upload(self, session: UploadSession) -> None:
        self._manifest_store.delete(session.transfer_id)
