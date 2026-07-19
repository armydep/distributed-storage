from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.dependencies.auth import CurrentUser, check_csrf, resolve_credential
from app.api.dependencies.database import DbSession
from app.core.cookies import (
    CSRF_HEADER_NAME,
    REFRESH_COOKIE_NAME,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.core.exceptions import AuthenticationError, CsrfError
from app.schemas.auth import (
    CookieLoginResponse,
    CookieRefreshResponse,
    RefreshTokenRequest,
    TokenResponse,
)
from app.schemas.user import UserCreate, UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
async def register(data: UserCreate, session: DbSession) -> UserResponse:
    user = await AuthService(session).register(data)
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse | CookieLoginResponse,
    summary="Log in and obtain a token pair",
)
async def login(
    request: Request,
    response: Response,
    session: DbSession,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    use_cookies: Annotated[bool, Form()] = False,
) -> TokenResponse | CookieLoginResponse:
    """OAuth2 password flow. ``username`` may be either the username or email.

    ``use_cookies=true`` switches to cookie-based sessions (for the browser
    SPA): both tokens are set as httpOnly cookies and never appear in the
    response body. Login has no prior credential for the dual-transport CSRF
    rule to gate on, so cookie-mode login requires the CSRF header directly -
    otherwise a cross-site form POST (form-urlencoded is CORS-safelisted, so
    it reaches the server unblocked) could log a victim into an attacker's
    account by planting session cookies. See docs/design/auth-cookies.md §5/§6.
    """
    if use_cookies and request.headers.get(CSRF_HEADER_NAME) != "1":
        raise CsrfError("Missing or invalid CSRF protection header")

    service = AuthService(session)
    user = await service.authenticate(form_data.username, form_data.password)
    tokens = await service.issue_tokens(user)

    if use_cookies:
        set_auth_cookies(
            response, access_token=tokens.access_token, refresh_token=tokens.refresh_token
        )
        return CookieLoginResponse(
            user=UserResponse.model_validate(user), expires_in=tokens.expires_in
        )
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse | CookieRefreshResponse,
    summary="Exchange a refresh token for a new pair",
)
async def refresh(
    request: Request,
    response: Response,
    session: DbSession,
    data: RefreshTokenRequest = RefreshTokenRequest(),
) -> TokenResponse | CookieRefreshResponse:
    """Accepts the refresh token from the request body, or falls back to the
    ``ds_refresh`` cookie when the body omits it (cookie-mode sessions)."""
    raw_token, from_cookie = resolve_credential(request, data.refresh_token, REFRESH_COOKIE_NAME)
    if raw_token is None:
        raise AuthenticationError("Refresh token is required")
    check_csrf(request, from_cookie=from_cookie)

    tokens = await AuthService(session).refresh(raw_token)

    if from_cookie:
        set_auth_cookies(
            response, access_token=tokens.access_token, refresh_token=tokens.refresh_token
        )
        return CookieRefreshResponse(expires_in=tokens.expires_in)
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    summary="Revoke a refresh token, ending the associated session",
)
async def logout(
    request: Request,
    response: Response,
    session: DbSession,
    _current_user: CurrentUser,
    data: RefreshTokenRequest = RefreshTokenRequest(),
) -> None:
    """Requires a valid access token/cookie (via ``CurrentUser``, which also
    enforces the CSRF check for cookie sessions). Clears both auth cookies
    unconditionally - a harmless no-op for clients that never had them."""
    raw_token, _from_cookie = resolve_credential(request, data.refresh_token, REFRESH_COOKIE_NAME)
    if raw_token is not None:
        await AuthService(session).logout(raw_token)
    clear_auth_cookies(response)
