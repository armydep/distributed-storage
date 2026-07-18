from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.conftest import _create_user


async def test_list_users(
    client: AsyncClient, admin_auth_headers: dict[str, str], regular_user: User
) -> None:
    response = await client.get("/api/v1/users", headers=admin_auth_headers)
    assert response.status_code == 200
    body = response.json()
    usernames = [item["username"] for item in body["items"]]
    assert regular_user.username in usernames
    assert body["pagination"]["total_items"] >= 2


async def test_list_users_pagination(
    client: AsyncClient, admin_auth_headers: dict[str, str], db_session: AsyncSession
) -> None:
    for i in range(5):
        await _create_user(
            db_session,
            email=f"paginate{i}@example.com",
            username=f"paginateuser{i}",
            password="Password123",
        )

    response = await client.get("/api/v1/users?page=1&page_size=3", headers=admin_auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 3
    assert body["pagination"]["page"] == 1
    assert body["pagination"]["page_size"] == 3
    assert body["pagination"]["total_pages"] >= 2


async def test_list_users_filter_by_role(
    client: AsyncClient, admin_auth_headers: dict[str, str], admin_user: User, regular_user: User
) -> None:
    response = await client.get("/api/v1/users?role=admin", headers=admin_auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert all(item["role"] == "admin" for item in body["items"])
    assert any(item["id"] == str(admin_user.id) for item in body["items"])


async def test_list_users_filter_by_active_status(
    client: AsyncClient, admin_auth_headers: dict[str, str], inactive_user: User
) -> None:
    response = await client.get("/api/v1/users?is_active=false", headers=admin_auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert all(item["is_active"] is False for item in body["items"])
    assert any(item["id"] == str(inactive_user.id) for item in body["items"])


async def test_list_users_search(
    client: AsyncClient, admin_auth_headers: dict[str, str], regular_user: User
) -> None:
    response = await client.get(
        f"/api/v1/users?search={regular_user.username}", headers=admin_auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert any(item["id"] == str(regular_user.id) for item in body["items"])


async def test_get_user_by_id(
    client: AsyncClient, admin_auth_headers: dict[str, str], regular_user: User
) -> None:
    response = await client.get(f"/api/v1/users/{regular_user.id}", headers=admin_auth_headers)
    assert response.status_code == 200
    assert response.json()["id"] == str(regular_user.id)


async def test_get_nonexistent_user_returns_404(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    response = await client.get(f"/api/v1/users/{uuid.uuid4()}", headers=admin_auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


async def test_update_user_as_admin(
    client: AsyncClient, admin_auth_headers: dict[str, str], regular_user: User
) -> None:
    response = await client.patch(
        f"/api/v1/users/{regular_user.id}",
        json={"username": "renamedbyadmin"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["username"] == "renamedbyadmin"


async def test_activate_user(
    client: AsyncClient, admin_auth_headers: dict[str, str], inactive_user: User
) -> None:
    response = await client.post(
        f"/api/v1/users/{inactive_user.id}/activate", headers=admin_auth_headers
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is True


async def test_deactivate_user(
    client: AsyncClient, admin_auth_headers: dict[str, str], regular_user: User
) -> None:
    response = await client.post(
        f"/api/v1/users/{regular_user.id}/deactivate", headers=admin_auth_headers
    )
    assert response.status_code == 200
    assert response.json()["is_active"] is False


async def test_admin_cannot_deactivate_self(
    client: AsyncClient, admin_auth_headers: dict[str, str], admin_user: User
) -> None:
    response = await client.post(
        f"/api/v1/users/{admin_user.id}/deactivate", headers=admin_auth_headers
    )
    assert response.status_code == 400


async def test_delete_user(
    client: AsyncClient, admin_auth_headers: dict[str, str], regular_user: User
) -> None:
    response = await client.delete(f"/api/v1/users/{regular_user.id}", headers=admin_auth_headers)
    assert response.status_code == 204

    follow_up = await client.get(f"/api/v1/users/{regular_user.id}", headers=admin_auth_headers)
    assert follow_up.status_code == 404


async def test_delete_nonexistent_user_returns_404(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    response = await client.delete(f"/api/v1/users/{uuid.uuid4()}", headers=admin_auth_headers)
    assert response.status_code == 404
