from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class EnvValidationResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def fatal(self) -> bool:
        return bool(self.errors)


def validate_environment() -> EnvValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    if not os.getenv("SUPABASE_URL", "").strip():
        errors.append("SUPABASE_URL is required")

    if not os.getenv("SUPABASE_ANON_KEY", "").strip():
        errors.append("SUPABASE_ANON_KEY is required")

    if not os.getenv("REMOTE_DESKTOP_JWT_SECRET", "").strip():
        warnings.append("REMOTE_DESKTOP_JWT_SECRET is not set (remote desktop auth disabled)")

    if not os.getenv("OTA_SIGNING_SECRET", "").strip():
        warnings.append("OTA_SIGNING_SECRET is not set (OTA disabled)")

    return EnvValidationResult(errors=errors, warnings=warnings)
