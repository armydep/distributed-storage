"""Authentication business logic: registration, login, token refresh/revocation.

Each public method defines its own transaction boundary (it commits, or lets
an exception propagate so the session is rolled back by ``get_db``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import AuthenticationError, ConflictError
from app.core.logging import get_logger
from app.core.security import (
    TokenExpiredError,
    TokenInvalidError,
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate

security_logger = get_logger("app.security")


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def register(self, data: UserCreate) -> User:
        email = data.email.lower()
        if await self._users.get_by_email(email) is not None:
            raise ConflictError("A user with this email already exists", details={"field": "email"})
        if await self._users.get_by_username(data.username) is not None:
            raise ConflictError(
                "A user with this username already exists", details={"field": "username"}
            )

        user = User(
            email=email, username=data.username, hashed_password=hash_password(data.password)
        )
        self._users.add(user)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError("A user with this email or username already exists") from exc
        await self._session.refresh(user)
        return user

    async def authenticate(self, identifier: str, password: str) -> User:
        user = await self._users.get_by_email_or_username(identifier)
        if user is None or not verify_password(password, user.hashed_password):
            security_logger.warning("Failed login attempt", extra={"identifier": identifier})
            raise AuthenticationError("Incorrect username/email or password")
        if not user.is_active:
            security_logger.warning(
                "Login attempt on disabled account", extra={"user_id": str(user.id)}
            )
            raise AuthenticationError("This account is disabled")
        return user

    async def issue_tokens(self, user: User) -> IssuedTokens:
        access_token, _access_expires_at = create_access_token(
            subject=str(user.id), role=user.role.value
        )
        raw_refresh_token, jti, refresh_expires_at = create_refresh_token(
            subject=str(user.id), role=user.role.value
        )
        self._refresh_tokens.add(
            RefreshToken(
                id=uuid.UUID(jti),
                user_id=user.id,
                token_hash=hash_refresh_token(raw_refresh_token),
                expires_at=refresh_expires_at,
            )
        )
        await self._session.commit()

        return IssuedTokens(
            access_token=access_token,
            refresh_token=raw_refresh_token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh(self, raw_refresh_token: str) -> IssuedTokens:
        try:
            decoded = decode_token(raw_refresh_token, expected_type=TokenType.REFRESH)
        except TokenExpiredError as exc:
            security_logger.warning("Expired refresh token used")
            raise AuthenticationError("Refresh token has expired") from exc
        except TokenInvalidError as exc:
            security_logger.warning("Invalid refresh token used")
            raise AuthenticationError("Refresh token is invalid") from exc

        stored = await self._refresh_tokens.get_by_id(uuid.UUID(decoded.jti))
        if stored is None or stored.token_hash != hash_refresh_token(raw_refresh_token):
            security_logger.warning("Unknown refresh token used")
            raise AuthenticationError("Refresh token is invalid")
        if stored.is_revoked:
            security_logger.warning(
                "Revoked refresh token reuse detected", extra={"user_id": str(stored.user_id)}
            )
            raise AuthenticationError("Refresh token has been revoked")
        if stored.expires_at < datetime.now(UTC):
            security_logger.warning(
                "Expired refresh token used", extra={"user_id": str(stored.user_id)}
            )
            raise AuthenticationError("Refresh token has expired")

        user = await self._users.get_by_id(stored.user_id)
        if user is None or not user.is_active:
            raise AuthenticationError("Account is no longer available")

        # Rotate: revoke the used refresh token and issue a brand new pair.
        await self._refresh_tokens.revoke(stored)
        return await self.issue_tokens(user)

    async def logout(self, raw_refresh_token: str) -> None:
        try:
            decoded = decode_token(raw_refresh_token, expected_type=TokenType.REFRESH)
        except (TokenExpiredError, TokenInvalidError):
            # Logout is idempotent from the client's perspective: an already
            # invalid/expired token requires no further action.
            return

        stored = await self._refresh_tokens.get_by_id(uuid.UUID(decoded.jti))
        if stored is not None and not stored.is_revoked:
            await self._refresh_tokens.revoke(stored)
            await self._session.commit()
