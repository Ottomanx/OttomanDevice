from __future__ import annotations

import hashlib
import hmac


def compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_sha256(data: bytes, expected_sha256: str) -> bool:
    normalized = expected_sha256.strip().lower()
    if len(normalized) != 64:
        return False

    return hmac.compare_digest(compute_sha256(data), normalized)


def compute_signature(sha256_hex: str, signing_secret: str) -> str:
    digest = hmac.new(
        signing_secret.encode("utf-8"),
        bytes.fromhex(sha256_hex),
        hashlib.sha256,
    )
    return digest.hexdigest()


def verify_signature(sha256_hex: str, signature: str, signing_secret: str) -> bool:
    if not signature:
        return False

    expected = compute_signature(sha256_hex, signing_secret)
    return hmac.compare_digest(expected.lower(), signature.strip().lower())


def parse_version(version: str) -> tuple[int, ...]:
    cleaned = version.strip().lower().removeprefix("v")
    parts: list[int] = []

    for segment in cleaned.split("."):
        digits = "".join(char for char in segment if char.isdigit())
        parts.append(int(digits) if digits else 0)

    return tuple(parts) if parts else (0,)


def is_newer_version(current_version: str, available_version: str) -> bool:
    return parse_version(available_version) > parse_version(current_version)
