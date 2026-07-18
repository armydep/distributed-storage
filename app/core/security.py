"""Password hashing and JWT access/refresh token helpers.

Kept intentionally framework-free (no FastAPI imports) so it can be reused
or extracted independently of the web layer.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

_password_hasher = PasswordHasher(
    time_cost=settings.PASSWORD_HASH_TIME_COST,
    memory_cost=settings.PASSWORD_HASH_MEMORY_COST,
    parallelism=settings.PASSWORD_HASH_PARALLELISM,
)


def hash_password(raw_password: str) -> str:
    return _password_hasher.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    try:
        return _password_hasher.verify(hashed_password, raw_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def hash_refresh_token(raw_token: str) -> str:
    """One-way digest used to look up / validate stored refresh tokens.

    We never store the raw refresh token, only this digest, so a database
    leak cannot be used to impersonate users.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenError(Exception):
    """Base class for token validation failures."""


class TokenExpiredError(TokenError):
    pass


class TokenInvalidError(TokenError):
    pass


@dataclass(frozen=True, slots=True)
class DecodedToken:
    subject: str
    role: str
    token_type: TokenType
    jti: str
    expires_at: datetime


def _create_token(
    *,
    subject: str,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
    jti: str | None = None,
) -> tuple[str, str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + expires_delta
    token_id = jti or str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": token_type.value,
        "jti": token_id,
        "iat": now,
        "exp": expires_at,
    }
    encoded = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded, token_id, expires_at


def create_access_token(*, subject: str, role: str) -> tuple[str, datetime]:
    token, _jti, expires_at = _create_token(
        subject=subject,
        role=role,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    return token, expires_at


def create_refresh_token(*, subject: str, role: str) -> tuple[str, str, datetime]:
    """Returns (raw_token, jti, expires_at). Caller persists hash(raw_token)."""
    return _create_token(
        subject=subject,
        role=role,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, *, expected_type: TokenType) -> DecodedToken:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("Token is invalid") from exc

    token_type = payload.get("type")
    if token_type != expected_type.value:
        raise TokenInvalidError(f"Expected a {expected_type.value} token")

    try:
        return DecodedToken(
            subject=payload["sub"],
            role=payload["role"],
            token_type=TokenType(token_type),
            jti=payload["jti"],
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
        )
    except (KeyError, ValueError) as exc:
        raise TokenInvalidError("Token payload is malformed") from exc
