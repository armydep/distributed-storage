"""Authentication and role-based authorization dependencies.

This is the *only* place authentication/authorization decisions are made.
Middleware never touches tokens or users; routes only ever depend on the
functions below.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer

from app.api.dependencies.database import DbSession
from app.core.config import settings
from app.core.cookies import ACCESS_COOKIE_NAME, CSRF_HEADER_NAME, UNSAFE_METHODS
from app.core.exceptions import AuthenticationError, AuthorizationError, CsrfError
from app.core.logging import get_logger
from app.core.security import TokenExpiredError, TokenInvalidError, TokenType, decode_token
from app.models.user import User, UserRole
from app.repositories.user import UserRepository

security_logger = get_logger("app.security")

# auto_error=False: a missing/absent bearer header must not short-circuit
# with FastAPI's own error before the cookie fallback (dual transport,
# see docs/design/auth-cookies.md §4) gets a chance to resolve a credential.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
    description="Obtain a token via /auth/login. Use the access token as a Bearer token.",
    auto_error=False,
)


def resolve_credential(
    request: Request, explicit: str | None, cookie_name: str
) -> tuple[str | None, bool]:
    """Prefer an explicitly supplied token (header or body); fall back to a cookie.

    Returns ``(token, from_cookie)``. Shared by ``get_current_user`` (bearer
    header vs. access cookie) and the ``/auth/refresh`` route (body field
    vs. refresh cookie), which resolve credentials from different sources
    but follow the identical precedence rule.
    """
    if explicit:
        return explicit, False
    return request.cookies.get(cookie_name), True


def check_csrf(request: Request, *, from_cookie: bool) -> None:
    """Enforce the custom-header CSRF check for cookie-authenticated mutations.

    Cookies attach to cross-site requests automatically; a request whose
    credential came from a header (or an explicit body field, e.g. a bearer
    client's own JSON) cannot be forged that way, so only cookie-sourced,
    state-changing requests are checked. Safe methods are always exempt.
    """
    if not from_cookie or request.method not in UNSAFE_METHODS:
        return
    if request.headers.get(CSRF_HEADER_NAME) != "1":
        raise CsrfError("Missing or invalid CSRF protection header")


async def get_current_user(
    request: Request,
    bearer_token: Annotated[str | None, Depends(oauth2_scheme)],
    session: DbSession,
) -> User:
    """Validates the access token (bearer header or ``ds_access`` cookie).

    Does not check ``is_active`` - use ``get_current_active_user`` for
    endpoints that must reject disabled accounts.
    """
    token, from_cookie = resolve_credential(request, bearer_token, ACCESS_COOKIE_NAME)
    if token is None:
        raise AuthenticationError("Not authenticated")
    check_csrf(request, from_cookie=from_cookie)

    try:
        decoded = decode_token(token, expected_type=TokenType.ACCESS)
    except TokenExpiredError as exc:
        raise AuthenticationError("Access token has expired") from exc
    except TokenInvalidError as exc:
        raise AuthenticationError("Access token is invalid") from exc

    try:
        user_id = uuid.UUID(decoded.subject)
    except ValueError as exc:
        raise AuthenticationError("Access token is invalid") from exc

    user = await UserRepository(session).get_by_id(user_id)
    if user is None:
        raise AuthenticationError("User for this token no longer exists")
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_active:
        security_logger.warning(
            "Access attempt by inactive user", extra={"user_id": str(current_user.id)}
        )
        raise AuthorizationError("This account is disabled")
    return current_user


CurrentUser = Annotated[User, Depends(get_current_active_user)]


def require_role(*allowed_roles: UserRole):
    """Dependency factory: allows access only to users with one of the given roles.

    Usage::

        @router.get("/admin-only")
        async def admin_only(current_user: User = Depends(require_role(UserRole.ADMIN))):
            ...
    """

    async def _require_role(current_user: CurrentUser) -> User:
        if current_user.role not in allowed_roles:
            security_logger.warning(
                "Forbidden operation attempted",
                extra={
                    "user_id": str(current_user.id),
                    "user_role": current_user.role.value,
                    "required_roles": [role.value for role in allowed_roles],
                },
            )
            raise AuthorizationError("You do not have permission to perform this action")
        return current_user

    return _require_role
