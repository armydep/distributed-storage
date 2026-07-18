from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.db.session import check_database_connection

router = APIRouter(tags=["health"])


@router.get("/health", summary="Liveness check")
async def health() -> dict[str, str]:
    """Returns 200 as long as the process is running and able to handle requests."""
    return {"status": "ok"}


@router.get("/ready", summary="Readiness check")
async def ready() -> JSONResponse:
    """Returns 200 only if the database is reachable, 503 otherwise."""
    is_ready = await check_database_connection()
    if not is_ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "database": "unreachable"},
        )
    return JSONResponse(
        status_code=status.HTTP_200_OK, content={"status": "ready", "database": "ok"}
    )
