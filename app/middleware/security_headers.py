"""Attach security-related response headers to every response.

API responses use a locked-down CSP. The interactive API documentation gets
the smallest additional allowances needed for FastAPI's CDN-hosted assets.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

_STRICT_CSP = "default-src 'none'; frame-ancestors 'none'"
_DOCUMENTATION_CSP = (
    "default-src 'none'; "
    "script-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "style-src https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src https://fastapi.tiangolo.com data:; "
    "connect-src 'self'; "
    "frame-ancestors 'none'"
)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, documentation_paths: set[str] | None = None) -> None:
        super().__init__(app)
        self.documentation_paths = documentation_paths or set()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        csp = _DOCUMENTATION_CSP if request.url.path in self.documentation_paths else _STRICT_CSP
        response.headers.setdefault("Content-Security-Policy", csp)
        return response
