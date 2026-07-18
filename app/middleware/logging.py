"""Logs one structured line per completed request.

Placed outside ``ProcessTimeMiddleware`` so ``request.state.process_time_ms``
is already populated by the time this middleware logs the response. Never
logs headers, cookies, or request/response bodies, so secrets (tokens,
passwords, authorization headers) cannot leak into logs.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger

logger = get_logger("app.request")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        logger.info(
            "request completed",
            extra={
                "http_method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": getattr(request.state, "process_time_ms", None),
                "client_host": request.client.host if request.client else None,
            },
        )
        return response
