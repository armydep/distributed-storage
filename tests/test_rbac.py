from __future__ import annotations

from httpx import AsyncClient

from app.models.user import User


async def test_admin_only_endpoint_allows_admin(
    client: AsyncClient, admin_auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/users", headers=admin_auth_headers)
    assert response.status_code == 200


async def test_regular_user_denied_admin_endpoint(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/api/v1/users", headers=auth_headers)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


async def test_inactive_user_denied_access(client: AsyncClient, inactive_user: User) -> None:
    from app.core.security import create_access_token

    token, _ = create_access_token(subject=str(inactive_user.id), role=inactive_user.role.value)
    response = await client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403


async def test_admin_can_manage_users(
    client: AsyncClient, admin_auth_headers: dict[str, str], regular_user: User
) -> None:
    response = await client.patch(
        f"/api/v1/users/{regular_user.id}",
        json={"role": "admin"},
        headers=admin_auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"


async def test_unauthenticated_request_rejected(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users")
    assert response.status_code == 401
