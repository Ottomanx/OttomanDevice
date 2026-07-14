from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RollbackManifest:
    current_version: str
    target_version: str
    package_id: str
    package_sha256: str
    package_signature: str
    storage_path: str
    prepared_at: str
    status: str = "rollback_ready"


def build_rollback_manifest(
    *,
    current_version: str,
    target_version: str,
    package_id: str,
    package_sha256: str,
    package_signature: str,
    storage_path: str,
) -> RollbackManifest:
    return RollbackManifest(
        current_version=current_version,
        target_version=target_version,
        package_id=package_id,
        package_sha256=package_sha256,
        package_signature=package_signature,
        storage_path=storage_path,
        prepared_at=datetime.now(timezone.utc).isoformat(),
    )


def write_rollback_manifest(download_dir: Path, manifest: RollbackManifest) -> Path:
    rollback_dir = download_dir / "rollback"
    rollback_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = rollback_dir / "current.json"
    payload: dict[str, Any] = asdict(manifest)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def read_rollback_manifest(download_dir: Path) -> RollbackManifest | None:
    manifest_path = download_dir / "rollback" / "current.json"
    if not manifest_path.exists():
        return None

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return RollbackManifest(**payload)
