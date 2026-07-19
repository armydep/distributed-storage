"""httpOnly cookie transport for JWT auth (see docs/design/auth-cookies.md).

Cookie names, the CSRF header name, and the two response mutations live
here so both the routes (set/clear) and the auth dependency chain
(read/check) share one source of truth.
"""

from __future__ import annotations

from starlette.responses import Response

from app.core.config import settings

ACCESS_COOKIE_NAME = "ds_access"
REFRESH_COOKIE_NAME = "ds_refresh"
CSRF_HEADER_NAME = "X-CSRF-Protection"

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

ACCESS_COOKIE_PATH = settings.API_V1_PREFIX
# Widened from the design doc's literal "/api/v1/auth/refresh": that scope
# would never be sent to /auth/logout (browsers match cookie Path as a
# prefix of the request path), yet logout also needs to read this cookie.
REFRESH_COOKIE_PATH = f"{settings.API_V1_PREFIX}/auth"


def set_auth_cookies(response: Response, *, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=True,
        samesite="none",
        path=ACCESS_COOKIE_PATH,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        httponly=True,
        secure=True,
        samesite="none",
        path=REFRESH_COOKIE_PATH,
    )


def clear_auth_cookies(response: Response) -> None:
    # path= is load-bearing: Response.delete_cookie defaults to path="/",
    # which would miss these scoped cookies entirely and silently no-op.
    response.delete_cookie(
        ACCESS_COOKIE_NAME, path=ACCESS_COOKIE_PATH, httponly=True, secure=True, samesite="none"
    )
    response.delete_cookie(
        REFRESH_COOKIE_NAME, path=REFRESH_COOKIE_PATH, httponly=True, secure=True, samesite="none"
    )
