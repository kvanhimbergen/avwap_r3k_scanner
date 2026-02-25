"""Tests for the scan chart-data endpoint."""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_parquet(cache_dir: Path, symbols: list[str] | None = None) -> None:
    """Create a minimal ohlcv_history.parquet for testing."""
    pd = pytest.importorskip("pandas")

    cache_dir.mkdir(parents=True, exist_ok=True)
    symbols = symbols or ["AAPL"]
    rows = []
    base_date = pd.Timestamp("2026-01-01")
    for sym in symbols:
        for i in range(30):
            d = base_date + pd.Timedelta(days=i)
            price = 100.0 + i * 0.5
            rows.append({
                "Date": d,
                "Ticker": sym,
                "Open": price - 0.5,
                "High": price + 1.0,
                "Low": price - 1.0,
                "Close": price,
                "Volume": float(1_000_000 + i * 10_000),
            })
    df = pd.DataFrame(rows)
    df.to_parquet(cache_dir / "ohlcv_history.parquet", engine="pyarrow")


def _make_client(tmp_path: Path):
    pytest.importorskip("duckdb")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from analytics_platform.backend.app import create_app
    from analytics_platform.backend.config import Settings

    settings = Settings(
        repo_root=tmp_path,
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "analytics.duckdb",
    )
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "cache").mkdir(exist_ok=True)
    app = create_app(settings=settings)
    return TestClient(app)


def test_chart_data_with_candles(tmp_path: Path) -> None:
    _make_parquet(tmp_path / "cache")
    client = _make_client(tmp_path)

    resp = client.get("/api/v1/scan/chart-data/AAPL")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["candles"]) == 30
    assert data["candles"][0]["open"] > 0
    assert data["candles"][0]["time"] == "2026-01-01"


def test_chart_data_unknown_symbol(tmp_path: Path) -> None:
    _make_parquet(tmp_path / "cache")
    client = _make_client(tmp_path)

    resp = client.get("/api/v1/scan/chart-data/ZZZZZ")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["candles"] == []


def test_chart_data_no_parquet(tmp_path: Path) -> None:
    client = _make_client(tmp_path)

    resp = client.get("/api/v1/scan/chart-data/AAPL")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["candles"] == []


def test_chart_data_with_avwap(tmp_path: Path) -> None:
    _make_parquet(tmp_path / "cache")
    client = _make_client(tmp_path)

    # Use a date in the middle of our 30-day range as anchor
    resp = client.get("/api/v1/scan/chart-data/AAPL?anchor=2026-01-10")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["candles"]) == 30
    assert len(data["avwap"]) > 0
    assert data["anchor_date"] == "2026-01-10"
    # AVWAP should start at or after anchor date
    assert data["avwap"][0]["time"] >= "2026-01-10"
