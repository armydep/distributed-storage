"""Data access for the User entity.

Repositories only talk to the database; they never commit transactions
(that is a service-layer responsibility) so callers can compose multiple
repository calls inside a single transaction boundary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


@dataclass(frozen=True, slots=True)
class UserListFilters:
    role: UserRole | None = None
    is_active: bool | None = None
    search: str | None = None


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        result = await self._session.execute(select(User).where(User.email == email.lower()))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_email_or_username(self, identifier: str) -> User | None:
        result = await self._session.execute(
            select(User).where(or_(User.email == identifier.lower(), User.username == identifier))
        )
        return result.scalar_one_or_none()

    async def list_users(
        self, *, filters: UserListFilters, offset: int, limit: int
    ) -> tuple[list[User], int]:
        conditions = []
        if filters.role is not None:
            conditions.append(User.role == filters.role)
        if filters.is_active is not None:
            conditions.append(User.is_active == filters.is_active)
        if filters.search:
            pattern = f"%{filters.search.lower()}%"
            conditions.append(
                or_(func.lower(User.username).like(pattern), func.lower(User.email).like(pattern))
            )

        base_query = select(User)
        count_query = select(func.count()).select_from(User)
        for condition in conditions:
            base_query = base_query.where(condition)
            count_query = count_query.where(condition)

        total = (await self._session.execute(count_query)).scalar_one()
        items_result = await self._session.execute(
            base_query.order_by(User.created_at.desc()).offset(offset).limit(limit)
        )
        return list(items_result.scalars().all()), total

    def add(self, user: User) -> None:
        self._session.add(user)

    async def delete(self, user: User) -> None:
        await self._session.delete(user)

    async def flush(self) -> None:
        await self._session.flush()
