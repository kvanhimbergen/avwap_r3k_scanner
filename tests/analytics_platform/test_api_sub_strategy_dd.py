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


def test_sub_strategy_dd_envelope(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    resp = client.get("/api/v1/sub-strategy-dd")
    assert resp.status_code == 200
    body = resp.json()
    assert "data" in body
    data = body["data"]
    assert "sleeves" in data
    assert isinstance(data["sleeves"], list)


def test_sub_strategy_dd_sleeve_shape(analytics_settings) -> None:
    client = _make_client(analytics_settings)
    data = client.get("/api/v1/sub-strategy-dd").json()["data"]
    # Either no sleeves (no coordinator runs in fixtures) or each one has the
    # right shape — the table reads these field names directly.
    for sleeve in data["sleeves"]:
        for key in (
            "key",
            "allocation_pct",
            "days",
            "final_equity",
            "peak_equity",
            "current_dd",
            "max_dd",
            "max_dd_date",
            "contribution_to_book_max_dd",
        ):
            assert key in sleeve, f"missing {key} in sleeve {sleeve}"
        # DDs are non-positive.
        assert sleeve["current_dd"] <= 0
        assert sleeve["max_dd"] <= 0
