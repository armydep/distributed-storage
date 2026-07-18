from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import UserRole
from app.repositories.user import UserRepository
from app.scripts.seed_users import _seed_user


async def test_seed_user_is_idempotent(db_session: AsyncSession) -> None:
    repo = UserRepository(db_session)
    credentials = {
        "email": "seed-user@example.com",
        "username": "seed_user",
        "password": "SeedPass123",
        "role": UserRole.USER,
    }

    assert await _seed_user(repo, **credentials) is True
    await db_session.commit()
    assert await _seed_user(repo, **credentials) is False

    user = await repo.get_by_username("seed_user")
    assert user is not None
    assert user.role == UserRole.USER
