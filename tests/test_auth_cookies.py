"""Cookie-transport auth tests (docs/design/auth-cookies.md).

Bearer-flow regression coverage lives in test_auth.py; this file covers
only what's new: cookie issuance/attributes, dual transport, CSRF
enforcement, and the login-CSRF fix found during implementation planning.
"""

from __future__ import annotations

from http.cookies import Morsel, SimpleCookie

from httpx import AsyncClient, Response

from app.core.cookies import (
    ACCESS_COOKIE_NAME,
    ACCESS_COOKIE_PATH,
    CSRF_HEADER_NAME,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
)
from app.models.user import User
from tests.conftest import REGULAR_USER_PASSWORD, make_expired_access_token

CSRF_HEADERS = {CSRF_HEADER_NAME: "1"}


def _set_cookies(response: Response, name: str) -> list[Morsel]:
    found = []
    for raw in response.headers.get_list("set-cookie"):
        jar = SimpleCookie()
        jar.load(raw)
        if name in jar:
            found.append(jar[name])
    return found


async def _login_with_cookies(client: AsyncClient, *, username: str, password: str) -> Response:
    return await client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password, "use_cookies": "true"},
        headers=CSRF_HEADERS,
    )


# --- Login (cookie mode) ----------------------------------------------------


async def test_login_with_cookies_sets_both_cookies(
    client: AsyncClient, regular_user: User
) -> None:
    response = await _login_with_cookies(
        client, username=regular_user.username, password=REGULAR_USER_PASSWORD
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["id"] == str(regular_user.id)
    assert body["expires_in"] > 0
    assert "access_token" not in body
    assert "refresh_token" not in body

    (access,) = _set_cookies(response, ACCESS_COOKIE_NAME)
    assert access["httponly"] is True
    assert access["secure"] is True
    assert access["samesite"] == "none"
    assert access["path"] == ACCESS_COOKIE_PATH

    (refresh,) = _set_cookies(response, REFRESH_COOKIE_NAME)
    assert refresh["httponly"] is True
    assert refresh["secure"] is True
    assert refresh["samesite"] == "none"
    assert refresh["path"] == REFRESH_COOKIE_PATH


async def test_login_without_cookies_flag_unchanged(
    client: AsyncClient, regular_user: User
) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": regular_user.username, "password": REGULAR_USER_PASSWORD},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert "set-cookie" not in response.headers


async def test_login_cookie_mode_requires_csrf_header(
    client: AsyncClient, regular_user: User
) -> None:
    """The fix for the login-CSRF gap found during planning: use_cookies=true
    without the header must be rejected, since /auth/login has no prior
    credential for the ordinary dual-transport CSRF rule to gate on."""
    response = await client.post(
        "/api/v1/auth/login",
        data={
            "username": regular_user.username,
            "password": REGULAR_USER_PASSWORD,
            "use_cookies": "true",
        },
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_HEADER_MISSING"


# --- Dual transport + CSRF on ordinary routes -------------------------------


async def test_cookie_authenticated_get_works_without_csrf_header(
    client: AsyncClient, regular_user: User
) -> None:
    await _login_with_cookies(
        client, username=regular_user.username, password=REGULAR_USER_PASSWORD
    )
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 200
    assert response.json()["id"] == str(regular_user.id)


async def test_cookie_authenticated_mutation_requires_csrf_header(
    client: AsyncClient, regular_user: User
) -> None:
    await _login_with_cookies(
        client, username=regular_user.username, password=REGULAR_USER_PASSWORD
    )

    without_header = await client.patch("/api/v1/users/me", json={"username": "renamedviacookie"})
    assert without_header.status_code == 403
    assert without_header.json()["error"]["code"] == "CSRF_HEADER_MISSING"

    with_header = await client.patch(
        "/api/v1/users/me", json={"username": "renamedviacookie"}, headers=CSRF_HEADERS
    )
    assert with_header.status_code == 200
    assert with_header.json()["username"] == "renamedviacookie"


async def test_bearer_mutation_does_not_require_csrf_header(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.patch(
        "/api/v1/users/me", json={"username": "renamedviabearer"}, headers=auth_headers
    )
    assert response.status_code == 200


# --- Refresh (cookie mode) ---------------------------------------------------


async def test_refresh_via_cookie_rotates_and_requires_csrf(
    client: AsyncClient, regular_user: User
) -> None:
    await _login_with_cookies(
        client, username=regular_user.username, password=REGULAR_USER_PASSWORD
    )

    without_header = await client.post("/api/v1/auth/refresh")
    assert without_header.status_code == 403
    assert without_header.json()["error"]["code"] == "CSRF_HEADER_MISSING"

    response = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["expires_in"] > 0
    assert "access_token" not in body
    assert len(_set_cookies(response, REFRESH_COOKIE_NAME)) == 1


async def test_refresh_cookie_reuse_after_rotation_rejected(
    client: AsyncClient, regular_user: User
) -> None:
    await _login_with_cookies(
        client, username=regular_user.username, password=REGULAR_USER_PASSWORD
    )
    old_refresh_cookie = client.cookies.get(REFRESH_COOKIE_NAME)

    first = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert first.status_code == 200

    # Replay the pre-rotation cookie explicitly - the jar now holds the
    # rotated one, so restore the old value at the same scoped path.
    client.cookies.set(REFRESH_COOKIE_NAME, old_refresh_cookie, path=REFRESH_COOKIE_PATH)
    second = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert second.status_code == 401


# --- Logout -------------------------------------------------------------------


async def test_logout_clears_cookies_and_revokes(client: AsyncClient, regular_user: User) -> None:
    await _login_with_cookies(
        client, username=regular_user.username, password=REGULAR_USER_PASSWORD
    )

    response = await client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)
    assert response.status_code == 204

    (access_clear,) = _set_cookies(response, ACCESS_COOKIE_NAME)
    assert access_clear["max-age"] == "0"
    assert access_clear["path"] == ACCESS_COOKIE_PATH

    (refresh_clear,) = _set_cookies(response, REFRESH_COOKIE_NAME)
    assert refresh_clear["max-age"] == "0"
    assert refresh_clear["path"] == REFRESH_COOKIE_PATH

    refresh_after_logout = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert refresh_after_logout.status_code == 401


async def test_logout_with_expired_access_cookie_but_live_refresh_cookie(
    client: AsyncClient, regular_user: User
) -> None:
    """Documents a non-obvious interaction: logout requires a *valid* access
    credential (via CurrentUser, unchanged behavior), so an expired access
    cookie 401s here even though the refresh cookie is still live. The
    design's SPA-side refresh-on-401 retry is what makes this transparent
    in practice - not something the backend papers over."""
    await _login_with_cookies(
        client, username=regular_user.username, password=REGULAR_USER_PASSWORD
    )
    expired = make_expired_access_token(regular_user.id)
    client.cookies.set(ACCESS_COOKIE_NAME, expired, path=ACCESS_COOKIE_PATH)

    response = await client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)
    assert response.status_code == 401


async def test_logout_requires_authentication_in_cookie_mode(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/logout", headers=CSRF_HEADERS)
    assert response.status_code == 401


# --- Cross-feature interactions ----------------------------------------------


async def test_password_change_revokes_cookie_session(
    client: AsyncClient, regular_user: User
) -> None:
    await _login_with_cookies(
        client, username=regular_user.username, password=REGULAR_USER_PASSWORD
    )

    response = await client.post(
        "/api/v1/users/me/change-password",
        json={"current_password": REGULAR_USER_PASSWORD, "new_password": "NewStrongPass1"},
        headers=CSRF_HEADERS,
    )
    assert response.status_code == 204

    refresh_after_change = await client.post("/api/v1/auth/refresh", headers=CSRF_HEADERS)
    assert refresh_after_change.status_code == 401


async def test_cors_credentialed_request_from_allowed_origin_succeeds(
    client: AsyncClient,
) -> None:
    response = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


async def test_cors_foreign_origin_gets_no_cors_headers(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert "access-control-allow-origin" not in response.headers
