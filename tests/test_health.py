from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_health_endpoint(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ready_endpoint_when_database_available(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"


async def test_ready_endpoint_when_database_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fail() -> bool:
        return False

    monkeypatch.setattr("app.api.routes.health.check_database_connection", _fail)
    response = await client.get("/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
