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


def test_regime_narrative_returns_envelope(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/regime-narrative")
    assert resp.status_code == 200
    body = resp.json()

    # Standard envelope.
    assert "data" in body
    assert "as_of_utc" in body

    data = body["data"]
    # Shape must include the keys the TodayStateCard reads.
    for key in (
        "regime",
        "days_in_regime",
        "reason",
        "hedge_state",
        "hedge_pct_of_book",
        "leveraged_used_pct",
        "leveraged_cap_pct",
    ):
        assert key in data, f"missing key {key} in payload"


def test_regime_narrative_includes_leverage_cap_pct(analytics_settings) -> None:
    """The cap must always be reported, even when no current usage."""
    client = _make_client(analytics_settings)
    data = client.get("/api/v1/regime-narrative").json()["data"]
    # Source-of-truth value mirrors strategies/raec_401k_v3.py max_leveraged_pct = 0.15
    assert data["leveraged_cap_pct"] == pytest.approx(15.0)


def test_regime_narrative_hedge_state_is_string(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    data = client.get("/api/v1/regime-narrative").json()["data"]
    assert data["hedge_state"] in {"active", "dormant", "unknown"}
