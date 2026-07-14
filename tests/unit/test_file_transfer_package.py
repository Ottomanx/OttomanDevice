from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest

from ottomandevice.remote_desktop.file_transfer import (
    Base64TransferTransport,
    BinaryTransferTransport,
    FixedChunkSizeStrategy,
    TransferManager,
    validate_relative_path,
)
from ottomandevice.remote_desktop.file_transfer.errors import FileTransferError
from ottomandevice.remote_desktop.file_transfer.queue import TransferWorkerPool
from ottomandevice.remote_desktop.file_transfer.sha256_stream import file_sha256


def test_validate_relative_path_rejects_traversal() -> None:
    assert validate_relative_path("../secret.txt") is None
    assert validate_relative_path("safe/path.txt") == "safe/path.txt"


def test_transport_round_trip() -> None:
    transport = Base64TransferTransport()
    payload = b"chunk-bytes"
    encoded = transport.encode_chunk(payload)
    assert isinstance(encoded, str)
    assert transport.decode_chunk(encoded) == payload


def test_binary_transport_round_trip() -> None:
    transport = BinaryTransferTransport()
    payload = b"binary-chunk"
    assert transport.decode_chunk(transport.encode_chunk(payload)) == payload


def test_chunk_size_strategy_configurable() -> None:
    strategy = FixedChunkSizeStrategy(131072)
    assert strategy.chunk_size() == 131072


@pytest.mark.asyncio
async def test_upload_streaming_finalize() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        manager = TransferManager(
            workspace_dir=workspace,
            max_file_size_bytes=1024 * 1024,
            chunk_size=16,
        )
        payload = b"hello streaming upload"
        session = await manager.initiate_upload(
            transfer_id="upload-1",
            relative_path="docs/stream.txt",
            total_size=len(payload),
        )
        await manager.handle_upload_chunk("upload-1", payload)
        path, size, digest = await manager.finalize_upload("upload-1")
        assert path == "docs/stream.txt"
        assert size == len(payload)
        assert (workspace / "docs" / "stream.txt").read_bytes() == payload
        assert digest is not None
        assert len(digest) == 64


@pytest.mark.asyncio
async def test_worker_pool_queues_beyond_two_workers() -> None:
    pool = TransferWorkerPool(max_workers=2)
    started: list[str] = []
    gate = asyncio.Event()

    def make_job(name: str):
        async def run() -> None:
            started.append(name)
            await gate.wait()

        return run

    await pool.submit("a", make_job("a"))
    await pool.submit("b", make_job("b"))
    await pool.submit("c", make_job("c"))
    await asyncio.sleep(0.05)
    assert pool.active_workers == 2
    assert pool.queued_count == 1
    gate.set()
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_download_streaming_chunks() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        target = workspace / "bin.dat"
        payload = b"x" * 100
        target.write_bytes(payload)

        manager = TransferManager(
            workspace_dir=workspace,
            max_file_size_bytes=1024 * 1024,
            chunk_size=32,
        )
        session = await manager.initiate_download(
            transfer_id="download-1",
            relative_path="bin.dat",
        )
        chunks: list[bytes] = []

        async def on_chunk(_transfer_id: str, chunk: bytes, _offset: int, _final: bool) -> None:
            chunks.append(chunk)

        async def on_progress(_transfer_id: str, _transferred: int, _total: int, _direction: str) -> None:
            return

        async def on_complete(
            _transfer_id: str,
            _path: str,
            _total: int,
            digest: str | None,
        ) -> None:
            assert digest == file_sha256(target)

        async def on_error(_transfer_id: str, _code: str, _message: str) -> None:
            raise AssertionError("download should not fail")

        await manager.queue_download(
            session,
            on_chunk=on_chunk,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
        )
        await asyncio.sleep(0.2)
        assert b"".join(chunks) == payload


@pytest.mark.asyncio
async def test_cancel_upload_removes_partial() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        manager = TransferManager(workspace_dir=workspace, max_file_size_bytes=1024, chunk_size=8)
        await manager.initiate_upload(
            transfer_id="cancel-1",
            relative_path="cancel.txt",
            total_size=32,
        )
        await manager.handle_upload_chunk("cancel-1", b"12345678")
        await manager.cancel_upload("cancel-1")
        assert manager.get_upload("cancel-1") is None
