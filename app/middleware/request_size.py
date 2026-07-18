"""Rejects requests whose declared body size exceeds the configured limit.

Checked against the ``Content-Length`` header before the body is read, so
oversized uploads are rejected immediately with ``413`` instead of being
buffered into memory first. Requests that omit ``Content-Length`` (e.g.
chunked transfer-encoding) are not covered by this check; a reverse proxy
or ASGI server body-size limit should be used as a defense-in-depth
complement in that case.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logging import correlation_id_ctx_var


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared_size = int(content_length)
            except ValueError:
                declared_size = 0
            if declared_size > settings.MAX_REQUEST_SIZE_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": (
                                "Request body exceeds the maximum allowed size of "
                                f"{settings.MAX_REQUEST_SIZE_BYTES} bytes"
                            ),
                            "details": None,
                            "correlation_id": correlation_id_ctx_var.get(),
                        }
                    },
                )
        return await call_next(request)
