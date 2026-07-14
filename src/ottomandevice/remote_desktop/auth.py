from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from threading import Lock
from collections.abc import Iterable
from typing import Any

from ottomandevice.permissions import normalize_permissions

import jwt

from ottomandevice.logging import get_logger

logger = get_logger("remote_desktop.auth")

JWT_REQUIRED_CLAIMS = ("device_id", "session_id", "iat", "exp", "jti")


class TokenValidationError(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class JwtSessionClaims:
    device_id: str
    session_id: str
    issued_at: int
    expires_at: int
    jti: str
    permissions: frozenset[str]
    user_id: str | None = None
    controller_name: str | None = None


class TokenReplayGuard:
    def __init__(self) -> None:
        self._used: dict[str, int] = {}
        self._lock = Lock()

    def mark_used(self, jti: str, expires_at: int) -> None:
        with self._lock:
            self._purge_locked()
            self._used[jti] = expires_at

    def is_used(self, jti: str) -> bool:
        with self._lock:
            self._purge_locked()
            return jti in self._used

    def _purge_locked(self) -> None:
        now = int(time.time())
        expired = [token_id for token_id, exp in self._used.items() if exp <= now]
        for token_id in expired:
            del self._used[token_id]


def create_session_jwt(
    *,
    device_id: str,
    session_id: str | None = None,
    secret: str,
    ttl_seconds: int,
    jti: str | None = None,
    issued_at: int | None = None,
    permissions: Iterable[str] | None = None,
    user_id: str | None = None,
    controller_name: str | None = None,
    algorithm: str = "HS256",
) -> str:
    if not secret:
        raise ValueError("JWT secret is required")

    now = issued_at if issued_at is not None else int(time.time())
    token_session_id = session_id or str(uuid.uuid4())
    token_jti = jti or str(uuid.uuid4())
    payload = {
        "device_id": device_id,
        "session_id": token_session_id,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": token_jti,
        "permissions": sorted(normalize_permissions(permissions)),
    }
    if user_id:
        payload["user_id"] = user_id
    if controller_name:
        payload["controller_name"] = controller_name
    return jwt.encode(payload, secret, algorithm=algorithm)


def _claims_from_payload(payload: dict[str, Any]) -> JwtSessionClaims:
    device_id = payload.get("device_id")
    session_id = payload.get("session_id")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    token_jti = payload.get("jti")

    if not isinstance(device_id, str) or not device_id:
        raise TokenValidationError("invalid_signature")
    if not isinstance(session_id, str) or not session_id:
        raise TokenValidationError("invalid_signature")
    if not isinstance(issued_at, int):
        raise TokenValidationError("invalid_signature")
    if not isinstance(expires_at, int):
        raise TokenValidationError("invalid_signature")
    if not isinstance(token_jti, str) or not token_jti:
        raise TokenValidationError("invalid_signature")

    permissions_raw = payload.get("permissions")
    if permissions_raw is not None and not isinstance(permissions_raw, list):
        raise TokenValidationError("invalid_signature")

    user_id = payload.get("user_id")
    if user_id is not None and (not isinstance(user_id, str) or not user_id):
        raise TokenValidationError("invalid_signature")

    controller_name = payload.get("controller_name")
    if controller_name is not None and not isinstance(controller_name, str):
        raise TokenValidationError("invalid_signature")

    return JwtSessionClaims(
        device_id=device_id,
        session_id=session_id,
        issued_at=issued_at,
        expires_at=expires_at,
        jti=token_jti,
        permissions=normalize_permissions(permissions_raw),
        user_id=user_id,
        controller_name=controller_name,
    )


def validate_session_token(
    token: str,
    *,
    device_id: str,
    secret: str,
    algorithm: str = "HS256",
    replay_guard: TokenReplayGuard | None = None,
) -> JwtSessionClaims:
    if not secret:
        logger.info("Session rejected")
        raise TokenValidationError("invalid_signature")

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            options={"require": list(JWT_REQUIRED_CLAIMS)},
        )
    except jwt.ExpiredSignatureError:
        logger.info("Token expired")
        raise TokenValidationError("expired") from None
    except jwt.InvalidTokenError:
        logger.info("Session rejected")
        raise TokenValidationError("invalid_signature") from None

    if not isinstance(payload, dict):
        logger.info("Session rejected")
        raise TokenValidationError("invalid_signature")

    claims = _claims_from_payload(payload)

    if claims.device_id != device_id:
        logger.info("Session rejected")
        raise TokenValidationError("wrong_device")

    if replay_guard is not None and replay_guard.is_used(claims.jti):
        logger.info("Token reused")
        raise TokenValidationError("reused")

    if replay_guard is not None:
        replay_guard.mark_used(claims.jti, claims.expires_at)

    logger.info("Session authenticated")
    return claims