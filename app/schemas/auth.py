from __future__ import annotations

from pydantic import BaseModel


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
    refresh_token: str
