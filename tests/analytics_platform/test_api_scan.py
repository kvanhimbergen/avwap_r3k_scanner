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


def test_scan_candidates(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/scan/candidates")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 2
    assert data["latest_date"] == "2026-02-10"
    assert len(data["rows"]) == 2
    # Sorted by trend_score DESC: AAPL (42.5) first, then TSLA (35.2)
    assert data["rows"][0]["symbol"] == "AAPL"
    assert data["rows"][1]["symbol"] == "TSLA"


def test_scan_candidates_filter_symbol(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/scan/candidates?symbol=AAPL")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 1
    assert data["rows"][0]["symbol"] == "AAPL"


def test_scan_candidates_filter_direction(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/scan/candidates?direction=short")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 1
    assert data["rows"][0]["direction"].lower() == "short"


def test_scan_candidates_empty(analytics_settings, tmp_path) -> None:
    """When CSV file does not exist, returns empty gracefully."""
    import os

    # Remove the CSV file
    csv_path = analytics_settings.repo_root / "daily_candidates.csv"
    if csv_path.exists():
        os.remove(csv_path)

    # Rebuild readmodels without the CSV
    pytest.importorskip("duckdb")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from analytics_platform.backend.app import create_app
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)
    app = create_app(settings=analytics_settings)
    client = TestClient(app)

    resp = client.get("/api/v1/scan/candidates")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 0
    assert data["rows"] == []


def test_scan_candidates_export(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/exports/scan_candidates.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
