from __future__ import annotations

import pytest


def _make_client(analytics_settings):
    pytest.importorskip("duckdb")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from analytics_platform.backend.app import create_app
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)
    app = create_app(settings=analytics_settings)
    return TestClient(app)


def test_data_freshness_envelope(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/data-freshness")
    assert resp.status_code == 200
    data = resp.json()["data"]
    for key in (
        "regime_e1",
        "schwab_snapshot",
        "coordinator",
        "scan_output",
        "token_health",
    ):
        assert key in data, f"missing {key}"


def test_data_freshness_token_health_shape(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    data = client.get("/api/v1/data-freshness").json()["data"]
    th = data["token_health"]
    assert isinstance(th, dict)
    assert "healthy" in th
    assert "days_until_expiry" in th
