"""Measures wall-clock time spent handling each request.

Runs as close to the route handler as possible so the recorded duration
reflects actual application work, not time spent in outer middleware.
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

PROCESS_TIME_HEADER = "X-Process-Time-Ms"


class ProcessTimeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        request.state.process_time_ms = duration_ms
        response.headers[PROCESS_TIME_HEADER] = str(duration_ms)
        return response
