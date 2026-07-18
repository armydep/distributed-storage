from __future__ import annotations

import logging
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.middleware.correlation_id import CORRELATION_ID_HEADER


async def test_correlation_id_is_generated_when_absent(client: AsyncClient) -> None:
    response = await client.get("/health")
    correlation_id = response.headers.get(CORRELATION_ID_HEADER)
    assert correlation_id is not None
    uuid.UUID(correlation_id)  # does not raise


async def test_valid_correlation_id_is_preserved(client: AsyncClient) -> None:
    supplied = str(uuid.uuid4())
    response = await client.get("/health", headers={CORRELATION_ID_HEADER: supplied})
    assert response.headers.get(CORRELATION_ID_HEADER) == supplied


async def test_invalid_correlation_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/health", headers={CORRELATION_ID_HEADER: "not-a-uuid"})
    returned = response.headers.get(CORRELATION_ID_HEADER)
    assert returned != "not-a-uuid"
    uuid.UUID(returned)  # does not raise


async def test_process_time_header_present(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert "X-Process-Time-Ms" in response.headers
    assert float(response.headers["X-Process-Time-Ms"]) >= 0


async def test_security_headers_present(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert response.headers.get("Content-Security-Policy") == (
        "default-src 'none'; frame-ancestors 'none'"
    )
    assert "Permissions-Policy" in response.headers


async def test_docs_csp_allows_required_assets(client: AsyncClient) -> None:
    response = await client.get("/api/v1/docs")
    assert response.status_code == 200
    csp = response.headers["Content-Security-Policy"]
    assert "script-src https://cdn.jsdelivr.net 'unsafe-inline'" in csp
    assert "style-src https://cdn.jsdelivr.net 'unsafe-inline'" in csp
    assert "connect-src 'self'" in csp


async def test_cors_allows_configured_origin(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


async def test_cors_rejects_unlisted_origin(client: AsyncClient) -> None:
    response = await client.get("/health", headers={"Origin": "http://evil.example.com"})
    assert "access-control-allow-origin" not in response.headers


async def test_trusted_host_rejects_unknown_host(app) -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://untrusted-host.example.com"
    ) as untrusted_client:
        response = await untrusted_client.get(
            "/health", headers={"Host": "untrusted-host.example.com"}
        )
    assert response.status_code == 400


async def test_oversized_request_returns_413(client: AsyncClient) -> None:
    oversized_username = "a" * 3000
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "big@example.com", "username": "biguser", "password": oversized_username},
    )
    assert response.status_code == 413


async def test_unexpected_exception_returns_consistent_json(
    app, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(self, data):
        raise RuntimeError("something exploded internally")

    monkeypatch.setattr("app.services.auth.AuthService.register", _boom)

    # Starlette's ServerErrorMiddleware re-raises the original exception
    # after sending the response (so it still reaches server-level logs);
    # httpx's default client would propagate that as a Python exception
    # instead of letting us inspect the response, so disable that here.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://testserver") as non_raising_client:
        response = await non_raising_client.post(
            "/api/v1/auth/register",
            json={"email": "boom@example.com", "username": "boomuser", "password": "StrongPass1"},
        )

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "something exploded internally" not in body["error"]["message"]
    assert "correlation_id" in body["error"]


async def test_sensitive_data_not_logged(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    secret_password = "SuperSecret123"
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "secretive@example.com",
            "username": "secretive",
            "password": secret_password,
        },
    )
    await client.post(
        "/api/v1/auth/login", data={"username": "secretive", "password": secret_password}
    )

    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert secret_password not in log_text
    assert "Bearer " not in log_text
