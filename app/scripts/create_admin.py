"""Safely bootstrap the first administrator account.

Usage (local):
    python -m app.scripts.create_admin \
        --email admin@example.com --username admin --password "S3curePass1"

Usage (Docker Compose):
    docker compose exec api python -m app.scripts.create_admin \
        --email admin@example.com --username admin --password "S3curePass1"

Credentials may also be supplied via environment variables so they never
appear in shell history:
    ADMIN_EMAIL, ADMIN_USERNAME, ADMIN_PASSWORD

Reuses the same UserCreate validation and password hashing the application
uses everywhere else, and refuses to create a duplicate administrator.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from pydantic import ValidationError

from app.core.logging import configure_logging, get_logger
from app.core.security import hash_password
from app.db.session import dispose_engine, session_scope
from app.models.user import User, UserRole
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate

logger = get_logger("app.scripts.create_admin")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create the first administrator account.")
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL"))
    parser.add_argument("--username", default=os.environ.get("ADMIN_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD"))
    return parser.parse_args()


async def create_admin(*, email: str, username: str, password: str) -> int:
    try:
        data = UserCreate(email=email, username=username, password=password)
    except ValidationError as exc:
        logger.error("Invalid administrator credentials", extra={"errors": exc.errors()})
        return 1

    async with session_scope() as session:
        repo = UserRepository(session)
        if await repo.get_by_email(data.email.lower()) is not None:
            logger.error("A user with this email already exists")
            return 1
        if await repo.get_by_username(data.username) is not None:
            logger.error("A user with this username already exists")
            return 1

        admin = User(
            email=data.email.lower(),
            username=data.username,
            hashed_password=hash_password(data.password),
            role=UserRole.ADMIN,
        )
        repo.add(admin)
        await session.commit()
        logger.info("Administrator created", extra={"user_id": str(admin.id)})

    return 0


def main() -> None:
    configure_logging()
    args = _parse_args()

    if not args.email or not args.username or not args.password:
        logger.error(
            "Missing required credentials: --email, --username and --password "
            "(or ADMIN_EMAIL / ADMIN_USERNAME / ADMIN_PASSWORD) are all required"
        )
        sys.exit(1)

    async def _run() -> int:
        try:
            return await create_admin(
                email=args.email, username=args.username, password=args.password
            )
        finally:
            # Disposing on the same loop the engine's connections were
            # opened on avoids asyncpg "attached to a different loop" errors.
            await dispose_engine()

    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
