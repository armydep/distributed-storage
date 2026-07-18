from __future__ import annotations

from httpx import AsyncClient

from app.models.user import User
from tests.conftest import REGULAR_USER_PASSWORD


async def test_get_current_user(
    client: AsyncClient, auth_headers: dict[str, str], regular_user: User
) -> None:
    response = await client.get("/api/v1/users/me", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(regular_user.id)
    assert body["username"] == regular_user.username


async def test_update_profile(client: AsyncClient, auth_headers: dict[str, str]) -> None:
    response = await client.patch(
        "/api/v1/users/me", json={"username": "updatedname"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["username"] == "updatedname"


async def test_update_profile_duplicate_email_rejected(
    client: AsyncClient, auth_headers: dict[str, str], admin_user: User
) -> None:
    response = await client.patch(
        "/api/v1/users/me", json={"email": admin_user.email}, headers=auth_headers
    )
    assert response.status_code == 409


async def test_change_password(
    client: AsyncClient, auth_headers: dict[str, str], regular_user: User
) -> None:
    response = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": REGULAR_USER_PASSWORD, "new_password": "NewStrongPass1"},
        headers=auth_headers,
    )
    assert response.status_code == 204

    login = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.username, "password": "NewStrongPass1"},
    )
    assert login.status_code == 200


async def test_change_password_wrong_current_password(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": "WrongCurrent1", "new_password": "NewStrongPass1"},
        headers=auth_headers,
    )
    assert response.status_code == 401
