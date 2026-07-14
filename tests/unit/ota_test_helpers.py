from __future__ import annotations

import io
import json
import zipfile


def make_firmware_zip(
    version: str,
    *,
    include_manifest: bool = True,
    manifest_version: str | None = None,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        if include_manifest:
            archive.writestr(
                "manifest.json",
                json.dumps({"version": manifest_version or version}),
            )
        archive.writestr("payload.txt", f"firmware-{version}")
    return buffer.getvalue()
