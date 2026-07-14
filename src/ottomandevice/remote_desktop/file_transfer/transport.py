from __future__ import annotations

import base64
import binascii
from abc import ABC, abstractmethod
from typing import Any


class TransferTransport(ABC):
    """Wire encoding for file chunks. TransferManager operates on raw bytes only."""

    @abstractmethod
    def encode_chunk(self, data: bytes) -> Any:
        raise NotImplementedError

    @abstractmethod
    def decode_chunk(self, value: Any) -> bytes | None:
        raise NotImplementedError


class Base64TransferTransport(TransferTransport):
    def encode_chunk(self, data: bytes) -> str:
        return base64.b64encode(data).decode("ascii")

    def decode_chunk(self, value: Any) -> bytes | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            return base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            return None


class BinaryTransferTransport(TransferTransport):
    """Placeholder for Sprint 39.5 binary WebSocket frames."""

    def encode_chunk(self, data: bytes) -> bytes:
        return data

    def decode_chunk(self, value: Any) -> bytes | None:
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        return None


def decode_chunk_payload(value: Any, transport: TransferTransport | None = None) -> bytes | None:
    adapter = transport or Base64TransferTransport()
    return adapter.decode_chunk(value)
