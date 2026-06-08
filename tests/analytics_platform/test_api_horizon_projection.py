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


def test_horizon_projection_returns_envelope(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/horizon-projection")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    data = body["data"]
    for key in (
        "current_age",
        "retirement_age",
        "years_to_retirement",
        "current_balance",
        "trailing_cagr",
        "projected_at_retirement",
        "goal_balance",
        "goal_pct",
        "verdict",
        "dd_series",
        "as_of_date",
    ):
        assert key in data, f"missing key {key} in payload"


def test_horizon_projection_age_arithmetic(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    data = client.get("/api/v1/horizon-projection").json()["data"]
    assert data["current_age"] == 51
    assert data["retirement_age"] == 65
    assert data["years_to_retirement"] == 14


def test_horizon_projection_dd_series_is_list(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    data = client.get("/api/v1/horizon-projection").json()["data"]
    assert isinstance(data["dd_series"], list)
    # Either empty (no snapshots) or each entry has the right shape.
    for point in data["dd_series"]:
        assert "date" in point
        assert "dd_pct" in point
        assert point["dd_pct"] <= 0  # drawdown is non-positive
