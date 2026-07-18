"""Shared pytest fixtures.

Tests run against a dedicated PostgreSQL database (``POSTGRES_DB=app_test``
by default), never the developer's normal database. Environment variables
are set here, before any ``app.*`` module is imported, because
``app.core.config.settings`` is instantiated once at import time.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

os.environ["ENVIRONMENT"] = "testing"
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ["POSTGRES_DB"] = os.environ.get("TEST_POSTGRES_DB", "app_test")
os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-automated-tests-only-32chars"
os.environ["MAX_REQUEST_SIZE_BYTES"] = "2048"
os.environ["TRUSTED_HOSTS"] = "testserver,localhost"
os.environ["CORS_ORIGINS"] = "http://localhost:3000"
os.environ["DEBUG"] = "true"

import jwt
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
)
from app.db.session import get_db
from app.main import app as fastapi_application
from app.models.refresh_token import RefreshToken
from app.models.user import User, UserRole

ROOT_DIR = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    cfg = Config(str(ROOT_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


# --- Session-wide setup ----------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations():
    # Plain sync fixture on purpose: Alembic's env.py drives its own
    # asyncio.run() internally, fully independent of pytest-asyncio's
    # per-test event loops. Running it as an async fixture would tie the
    # migration connection to one test's loop and break as soon as a
    # different test (with its own loop) tried to reuse it.
    command.upgrade(_alembic_config(), "head")
    yield
    command.downgrade(_alembic_config(), "base")


@pytest_asyncio.fixture
async def db_engine(_apply_migrations: None) -> AsyncIterator[AsyncEngine]:
    # Function-scoped (not session-scoped): pytest-asyncio gives each test
    # function its own event loop by default, and asyncpg connections are
    # bound to the loop they were created on, so a shared engine would
    # break as soon as it crossed test boundaries.
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def clean_database(db_engine: AsyncEngine) -> AsyncIterator[None]:
    """Truncates all tables after every test so tests never depend on order."""
    yield
    async with db_engine.begin() as connection:
        await connection.execute(
            text("TRUNCATE TABLE refresh_tokens, users RESTART IDENTITY CASCADE")
        )


# --- Core fixtures required by the task spec -------------------------------


@pytest.fixture(scope="session")
def app():
    """The FastAPI application under test."""
    return fastapi_application


@pytest_asyncio.fixture
async def db_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(
    app, session_factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[AsyncClient]:
    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
    app.dependency_overrides.clear()


async def _create_user(
    session: AsyncSession,
    *,
    email: str,
    username: str,
    password: str,
    role: UserRole = UserRole.USER,
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        username=username,
        hashed_password=hash_password(password),
        role=role,
        is_active=is_active,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


REGULAR_USER_PASSWORD = "Password123"
ADMIN_USER_PASSWORD = "AdminPass123"
INACTIVE_USER_PASSWORD = "Password123"


@pytest_asyncio.fixture
async def regular_user(db_session: AsyncSession) -> User:
    return await _create_user(
        db_session, email="user@example.com", username="regularuser", password=REGULAR_USER_PASSWORD
    )


@pytest_asyncio.fixture
async def active_user(regular_user: User) -> User:
    return regular_user


@pytest_asyncio.fixture
async def admin_user(db_session: AsyncSession) -> User:
    return await _create_user(
        db_session,
        email="admin@example.com",
        username="adminuser",
        password=ADMIN_USER_PASSWORD,
        role=UserRole.ADMIN,
    )


@pytest_asyncio.fixture
async def inactive_user(db_session: AsyncSession) -> User:
    return await _create_user(
        db_session,
        email="inactive@example.com",
        username="inactiveuser",
        password=INACTIVE_USER_PASSWORD,
        is_active=False,
    )


@pytest.fixture
def access_token(regular_user: User) -> str:
    token, _ = create_access_token(subject=str(regular_user.id), role=regular_user.role.value)
    return token


@pytest.fixture
def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
def admin_access_token(admin_user: User) -> str:
    token, _ = create_access_token(subject=str(admin_user.id), role=admin_user.role.value)
    return token


@pytest.fixture
def admin_auth_headers(admin_access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_access_token}"}


@pytest_asyncio.fixture
async def refresh_token(db_session: AsyncSession, regular_user: User) -> str:
    raw_token, jti, expires_at = create_refresh_token(
        subject=str(regular_user.id), role=regular_user.role.value
    )
    db_session.add(
        RefreshToken(
            id=uuid.UUID(jti),
            user_id=regular_user.id,
            token_hash=hash_refresh_token(raw_token),
            expires_at=expires_at,
        )
    )
    await db_session.commit()
    return raw_token


def make_expired_access_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": UserRole.USER.value,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": now - timedelta(minutes=30),
        "exp": now - timedelta(minutes=15),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def make_expired_refresh_token(user_id: uuid.UUID) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "role": UserRole.USER.value,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "iat": now - timedelta(days=40),
        "exp": now - timedelta(days=10),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
