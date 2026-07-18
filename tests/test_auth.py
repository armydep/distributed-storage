from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.conftest import (
    INACTIVE_USER_PASSWORD,
    REGULAR_USER_PASSWORD,
    make_expired_access_token,
    make_expired_refresh_token,
)

# --- Registration -----------------------------------------------------------


async def test_register_success(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "new@example.com", "username": "newuser", "password": "StrongPass1"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    assert body["username"] == "newuser"
    assert body["role"] == "user"
    assert body["is_active"] is True
    assert "hashed_password" not in body
    assert "password" not in body


async def test_register_duplicate_email_rejected(client: AsyncClient, regular_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": regular_user.email, "username": "someoneelse", "password": "StrongPass1"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_register_duplicate_username_rejected(
    client: AsyncClient, regular_user: User
) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "username": regular_user.username,
            "password": "StrongPass1",
        },
    )
    assert response.status_code == 409


async def test_register_invalid_email_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "username": "validuser", "password": "StrongPass1"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_register_invalid_password_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "username": "weakpassuser", "password": "short"},
    )
    assert response.status_code == 422


# --- Login --------------------------------------------------------------


async def test_login_success(client: AsyncClient, regular_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.username, "password": REGULAR_USER_PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] > 0


async def test_login_with_email_also_works(client: AsyncClient, regular_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.email, "password": REGULAR_USER_PASSWORD},
    )
    assert response.status_code == 200


async def test_login_invalid_password(client: AsyncClient, regular_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.username, "password": "WrongPassword1"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_FAILED"


async def test_login_nonexistent_user(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", data={"username": "ghost", "password": "Whatever123"}
    )
    assert response.status_code == 401


async def test_login_inactive_user(client: AsyncClient, inactive_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": inactive_user.username, "password": INACTIVE_USER_PASSWORD},
    )
    assert response.status_code == 401


# --- Access token validation ----------------------------------------------


async def test_access_token_validates_current_user(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200


async def test_expired_access_token_rejected(client: AsyncClient, regular_user: User) -> None:
    token = make_expired_access_token(regular_user.id)
    response = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_invalid_access_token_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/users/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401


async def test_missing_access_token_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401


# --- Refresh flow ---------------------------------------------------------


async def test_refresh_flow_issues_new_tokens(client: AsyncClient, refresh_token: str) -> None:
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"] != refresh_token


async def test_expired_refresh_token_rejected(client: AsyncClient, regular_user: User) -> None:
    token = make_expired_refresh_token(regular_user.id)
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert response.status_code == 401


async def test_revoked_refresh_token_rejected(
    client: AsyncClient, db_session: AsyncSession, refresh_token: str, regular_user: User
) -> None:
    from app.models.refresh_token import RefreshToken

    result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.user_id == regular_user.id)
    )
    stored = result.scalar_one()
    stored.revoked_at = stored.created_at
    await db_session.commit()

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401


async def test_reuse_of_rotated_refresh_token_rejected(
    client: AsyncClient, refresh_token: str
) -> None:
    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert first.status_code == 200

    second = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert second.status_code == 401


# --- Logout ---------------------------------------------------------------


async def test_logout_revokes_refresh_token(
    client: AsyncClient, auth_headers: dict[str, str], refresh_token: str
) -> None:
    response = await client.post(
        "/api/v1/auth/logout", json={"refresh_token": refresh_token}, headers=auth_headers
    )
    assert response.status_code == 204

    refresh_response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert refresh_response.status_code == 401


async def test_logout_requires_authentication(client: AsyncClient, refresh_token: str) -> None:
    response = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert response.status_code == 401
