from __future__ import annotations

import hashlib
from pathlib import Path


class Sha256Stream:
    def __init__(self) -> None:
        self._hasher = hashlib.sha256()

    def update(self, data: bytes) -> None:
        self._hasher.update(data)

    def hexdigest(self) -> str:
        return self._hasher.hexdigest()


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(65536)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()
