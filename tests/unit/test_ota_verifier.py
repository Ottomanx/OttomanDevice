from __future__ import annotations


from ottomandevice.ota.rollback import build_rollback_manifest, read_rollback_manifest, write_rollback_manifest
from ottomandevice.ota.verifier import (
    compute_sha256,
    compute_signature,
    is_newer_version,
    verify_sha256,
    verify_signature,
)

TEST_SECRET = "dev-ota-signing-secret-change-in-production"
SAMPLE_PACKAGE = b"firmware-package-v0.2.0"


def test_compute_and_verify_sha256() -> None:
    digest = compute_sha256(SAMPLE_PACKAGE)

    assert len(digest) == 64
    assert verify_sha256(SAMPLE_PACKAGE, digest) is True


def test_sha256_verification_rejects_invalid_package() -> None:
    digest = compute_sha256(SAMPLE_PACKAGE)

    assert verify_sha256(b"tampered-package", digest) is False
    assert verify_sha256(SAMPLE_PACKAGE, "0" * 64) is False


def test_signature_verification_success() -> None:
    digest = compute_sha256(SAMPLE_PACKAGE)
    signature = compute_signature(digest, TEST_SECRET)

    assert verify_signature(digest, signature, TEST_SECRET) is True


def test_signature_verification_rejects_invalid_package() -> None:
    digest = compute_sha256(SAMPLE_PACKAGE)
    signature = compute_signature(digest, TEST_SECRET)

    assert verify_signature(digest, "deadbeef", TEST_SECRET) is False
    assert verify_signature("0" * 64, signature, TEST_SECRET) is False
    assert verify_signature(digest, signature, "wrong-secret") is False


def test_version_check_detects_newer_release() -> None:
    assert is_newer_version("0.1.0", "0.2.0") is True
    assert is_newer_version("0.2.0", "0.2.0") is False
    assert is_newer_version("0.3.1", "0.3.0") is False


def test_rollback_preparation_writes_manifest(tmp_path) -> None:
    manifest = build_rollback_manifest(
        current_version="0.1.0",
        target_version="0.2.0",
        package_id="pkg-123",
        package_sha256=compute_sha256(SAMPLE_PACKAGE),
        package_signature=compute_signature(compute_sha256(SAMPLE_PACKAGE), TEST_SECRET),
        storage_path="0.2.0/firmware.zip",
    )

    manifest_path = write_rollback_manifest(tmp_path, manifest)
    loaded = read_rollback_manifest(tmp_path)

    assert manifest_path.exists()
    assert loaded is not None
    assert loaded.current_version == "0.1.0"
    assert loaded.target_version == "0.2.0"
    assert loaded.status == "rollback_ready"
