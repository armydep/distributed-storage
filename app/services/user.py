"""User-management business logic (profile, password, and admin operations)."""

from __future__ import annotations

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserListFilters, UserRepository
from app.schemas.common import PaginationMetadata
from app.schemas.user import PasswordChangeRequest, UserAdminUpdate, UserUpdate

security_logger = get_logger("app.security")


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._users = UserRepository(session)
        self._refresh_tokens = RefreshTokenRepository(session)

    async def get_by_id_or_raise(self, user_id: uuid.UUID) -> User:
        user = await self._users.get_by_id(user_id)
        if user is None:
            raise NotFoundError("The requested user was not found")
        return user

    async def list_users(
        self, *, filters: UserListFilters, page: int, page_size: int
    ) -> tuple[list[User], PaginationMetadata]:
        offset = (page - 1) * page_size
        items, total = await self._users.list_users(filters=filters, offset=offset, limit=page_size)
        metadata = PaginationMetadata.build(page=page, page_size=page_size, total_items=total)
        return items, metadata

    async def _apply_email_username_change(
        self, user: User, *, email: str | None, username: str | None
    ) -> None:
        if email is not None and email.lower() != user.email:
            existing = await self._users.get_by_email(email)
            if existing is not None and existing.id != user.id:
                raise ConflictError(
                    "A user with this email already exists", details={"field": "email"}
                )
            user.email = email.lower()
        if username is not None and username != user.username:
            existing = await self._users.get_by_username(username)
            if existing is not None and existing.id != user.id:
                raise ConflictError(
                    "A user with this username already exists", details={"field": "username"}
                )
            user.username = username

    async def update_profile(self, user: User, data: UserUpdate) -> User:
        await self._apply_email_username_change(user, email=data.email, username=data.username)
        await self._commit_or_conflict(user)
        return user

    async def change_password(self, user: User, data: PasswordChangeRequest) -> None:
        if not verify_password(data.current_password, user.hashed_password):
            raise AuthenticationError("Current password is incorrect")
        user.hashed_password = hash_password(data.new_password)
        # Invalidate all existing sessions so a leaked/old password can no
        # longer be used to mint new access tokens via a stale refresh token.
        await self._refresh_tokens.revoke_all_for_user(user.id)
        await self._session.commit()
        security_logger.info("Password changed", extra={"user_id": str(user.id)})

    async def admin_update(self, user: User, data: UserAdminUpdate) -> User:
        await self._apply_email_username_change(user, email=data.email, username=data.username)
        if data.role is not None:
            user.role = data.role
        if data.is_active is not None:
            await self._set_active(user, data.is_active)
        await self._commit_or_conflict(user)
        return user

    async def set_active(self, user: User, is_active: bool) -> User:
        await self._set_active(user, is_active)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def _set_active(self, user: User, is_active: bool) -> None:
        if not is_active and user.is_active:
            await self._refresh_tokens.revoke_all_for_user(user.id)
            security_logger.info("User deactivated", extra={"user_id": str(user.id)})
        user.is_active = is_active

    async def delete_user(self, user: User) -> None:
        await self._refresh_tokens.revoke_all_for_user(user.id)
        await self._users.delete(user)
        await self._session.commit()

    async def _commit_or_conflict(self, user: User) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ConflictError("A user with this email or username already exists") from exc
        await self._session.refresh(user)
