from __future__ import annotations

from pydantic import BaseModel

from app.schemas.user import UserResponse


class LoginRequest(BaseModel):
    """JSON-body login schema, documented for API consumers.

    The actual ``/auth/login`` endpoint accepts
    ``OAuth2PasswordRequestForm`` (form-encoded ``username``/``password``)
    instead, per the OAuth2 password-flow convention FastAPI's interactive
    docs and ``OAuth2PasswordBearer`` dependency expect. This schema is kept
    for clients that prefer documenting the same semantics as JSON.
    """

    username_or_email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshTokenRequest(BaseModel):
    """``refresh_token`` is optional so cookie-mode clients can omit it (or send
    ``{}``) and let the server fall back to the ``ds_refresh`` cookie instead."""

    refresh_token: str | None = None


class CookieLoginResponse(BaseModel):
    """Returned by ``/auth/login``/``/auth/refresh`` in cookie mode.

    Deliberately carries no raw token: the whole point of httpOnly cookies
    is that the SPA's JavaScript never sees one, including in a response body.
    """

    user: UserResponse
    expires_in: int


class CookieRefreshResponse(BaseModel):
    expires_in: int
