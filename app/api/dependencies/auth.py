"""Authentication and role-based authorization dependencies.

This is the *only* place authentication/authorization decisions are made.
Middleware never touches tokens or users; routes only ever depend on the
functions below.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

from app.api.dependencies.database import DbSession
from app.core.config import settings
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.logging import get_logger
from app.core.security import TokenExpiredError, TokenInvalidError, TokenType, decode_token
from app.models.user import User, UserRole
from app.repositories.user import UserRepository

security_logger = get_logger("app.security")

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/auth/login",
    description="Obtain a token via /auth/login. Use the access token as a Bearer token.",
)


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    session: DbSession,
) -> User:
    """Validates the bearer access token and loads the corresponding user.

    Does not check ``is_active`` - use ``get_current_active_user`` for
    endpoints that must reject disabled accounts.
    """
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
