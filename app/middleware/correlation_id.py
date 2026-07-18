"""Assigns every request a correlation (request) ID.

Accepts a caller-supplied ``X-Correlation-ID`` header if it is a valid
UUID, otherwise generates a fresh one. The ID is exposed to the rest of the
application via a contextvar (for logging) and ``request.state``, and is
always echoed back in the response header.
"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import correlation_id_ctx_var

CORRELATION_ID_HEADER = "X-Correlation-ID"


def _extract_or_generate(request: Request) -> str:
    incoming = request.headers.get(CORRELATION_ID_HEADER)
    if incoming:
        try:
            return str(uuid.UUID(incoming))
        except ValueError:
            pass
    return str(uuid.uuid4())


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        correlation_id = _extract_or_generate(request)
        request.state.correlation_id = correlation_id
        token = correlation_id_ctx_var.set(correlation_id)
        try:
            response = await call_next(request)
        finally:
            correlation_id_ctx_var.reset(token)
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        return response
