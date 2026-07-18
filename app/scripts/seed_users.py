"""Seed one development account for each application role.

The command is idempotent: accounts that already exist with the expected
username and role are left unchanged. It refuses to run in production.
"""

from __future__ import annotations

import asyncio
import os
import sys

from pydantic import ValidationError

from app.core.config import Environment, settings
from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db.session import dispose_engine, session_scope
from app.models.user import User, UserRole
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate

logger = get_logger("app.scripts.seed_users")


async def _seed_user(
    repo: UserRepository,
    *,
    email: str,
    username: str,
    password: str,
    role: UserRole,
) -> bool:
    data = UserCreate(email=email, username=username, password=password)
    existing = await repo.get_by_email(data.email.lower())
    if existing is None:
        existing = await repo.get_by_username(data.username)

    if existing is not None:
        if existing.email != data.email.lower() or existing.username != data.username:
            raise ValueError(f"Seed account conflicts with existing user: {data.username}")
        if existing.role != role:
            raise ValueError(f"Seed account has unexpected role: {data.username}")
        logger.info("Seed user already exists", extra={"username": username, "role": role.value})
        return False

    repo.add(
        User(
            email=data.email.lower(),
            username=data.username,
            hashed_password=hash_password(data.password),
            role=role,
        )
    )
    logger.info("Seed user created", extra={"username": username, "role": role.value})
    return True


async def seed_users() -> int:
    if settings.ENVIRONMENT == Environment.PRODUCTION:
        logger.error("Development users cannot be seeded in production")
        return 1

    credentials = (
        (
            os.environ.get("SEED_USER_EMAIL", "user@example.com"),
            os.environ.get("SEED_USER_USERNAME", "user"),
            os.environ.get("SEED_USER_PASSWORD", "UserPass123"),
            UserRole.USER,
        ),
        (
            os.environ.get("SEED_ADMIN_EMAIL", "admin@example.com"),
            os.environ.get("SEED_ADMIN_USERNAME", "admin"),
            os.environ.get("SEED_ADMIN_PASSWORD", "AdminPass123"),
            UserRole.ADMIN,
        ),
    )

    try:
        async with session_scope() as session:
            repo = UserRepository(session)
            for email, username, password, role in credentials:
                await _seed_user(
                    repo,
                    email=email,
                    username=username,
                    password=password,
                    role=role,
                )
            await session.commit()
    except (ValidationError, ValueError) as exc:
        logger.error("Unable to seed development users", extra={"reason": str(exc)})
        return 1

    return 0


def main() -> None:
    configure_logging()

    async def _run() -> int:
        try:
            return await seed_users()
        finally:
            await dispose_engine()

    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
