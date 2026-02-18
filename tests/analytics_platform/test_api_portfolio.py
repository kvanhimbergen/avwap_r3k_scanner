from __future__ import annotations

import pytest


def _make_client(analytics_settings):
    """Shared boilerplate: importorskip, build readmodels, return TestClient."""
    pytest.importorskip("duckdb")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from analytics_platform.backend.app import create_app
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)
    app = create_app(settings=analytics_settings)
    return TestClient(app)


def test_portfolio_overview(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/portfolio/overview")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "latest" in data
    assert data["latest"]["capital_total"] == 100000.0


def test_portfolio_positions(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/portfolio/positions")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "by_strategy" in data
    # Flatten all positions across strategy groups
    all_positions = [
        p
        for group in data["by_strategy"]
        for p in group.get("positions", [])
    ]
    assert len(all_positions) >= 3  # AAPL, MSFT, TQQQ from fixture


def test_portfolio_history(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/portfolio/history")
    assert resp.status_code == 200
    data = resp.json()["data"]
    points = data.get("points", data) if isinstance(data, dict) else data
    assert isinstance(points, list)
    assert len(points) >= 1


def test_strategy_matrix(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/strategies/matrix")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "strategies" in data


def test_portfolio_exports(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/exports/portfolio_positions.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
