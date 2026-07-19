"""Application-level exceptions.

Services and repositories raise these instead of HTTPException so that
business logic stays free of HTTP concerns. The API layer (see
app/core/error_handlers.py) translates them into consistent JSON responses.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all handled application errors."""

    status_code: int = 400
    code: str = "APPLICATION_ERROR"

    def __init__(self, message: str, *, details: object | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class AuthenticationError(AppError):
    status_code = 401
    code = "AUTHENTICATION_FAILED"


class AuthorizationError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class InvalidStateError(AppError):
    status_code = 400
    code = "INVALID_STATE"


class CsrfError(AppError):
    status_code = 403
    code = "CSRF_HEADER_MISSING"
