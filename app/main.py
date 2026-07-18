"""FastAPI application entry point: wiring only.

Routing, middleware, and exception-handler registration live here;
business logic lives in services, persistence in repositories/models.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_v1_router
from app.api.routes import health
from app.core.config import settings
from app.core.error_handlers import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db.session import check_database_connection, dispose_engine
from app.middleware.correlation_id import CorrelationIdMiddleware
from app.middleware.logging import RequestLoggingMiddleware
from app.middleware.process_time import ProcessTimeMiddleware
from app.middleware.request_size import RequestSizeLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

configure_logging()
logger = get_logger("app.lifecycle")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "Application starting",
        extra={
            "app_name": settings.APP_NAME,
            "app_version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT.value,
        },
    )
    if await check_database_connection():
        logger.info("Database connectivity verified")
    else:
        logger.warning("Database is not reachable at startup; readiness checks will fail")

    yield

    await dispose_engine()
    logger.info("Application shutdown complete")


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Production-oriented FastAPI + PostgreSQL backend scaffold with JWT "
        "authentication, refresh-token rotation, and role-based access control."
    ),
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    docs_url=f"{settings.API_V1_PREFIX}/docs",
    redoc_url=f"{settings.API_V1_PREFIX}/redoc",
    lifespan=lifespan,
)

# --- Middleware registration ---------------------------------------------
# Starlette wraps middleware in the reverse order they are added: the LAST
# middleware added here becomes the OUTERMOST layer and therefore runs
# FIRST on the way in and LAST on the way out. We add them innermost-first
# so the effective request execution order (outer -> inner) reads:
#
#   TrustedHost -> CORS -> SecurityHeaders -> RequestSizeLimit -> GZip
#     -> CorrelationId -> RequestLogging -> ProcessTime -> route handler
#
# Rationale:
#   * TrustedHost is outermost: reject requests with a forged Host header
#     before any other work happens.
#   * CORS sits next so preflight/CORS headers are applied consistently,
#     including on error responses produced further in.
#   * SecurityHeaders wraps almost everything so every response - including
#     errors - carries the hardening headers.
#   * RequestSizeLimit runs before the body would otherwise be read.
#   * GZip compresses the final response body.
#   * CorrelationId must run before RequestLogging so every log line for
#     this request can include the correlation ID.
#   * ProcessTime is innermost so its timer wraps only actual application
#     work (routing + endpoint + dependencies), not other middleware.
app.add_middleware(ProcessTimeMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(
    SecurityHeadersMiddleware,
    documentation_paths={
        f"{settings.API_V1_PREFIX}/docs",
        f"{settings.API_V1_PREFIX}/redoc",
        f"{settings.API_V1_PREFIX}/docs/oauth2-redirect",
    },
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials="*" not in settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID", "X-Process-Time-Ms"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.TRUSTED_HOSTS)

register_exception_handlers(app)

app.include_router(health.router)
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)
