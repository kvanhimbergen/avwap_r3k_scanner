"""Tests for the trade log CRUD endpoints and TradeLogStore."""
from __future__ import annotations

from pathlib import Path

import pytest


def _make_store(tmp_path: Path):
    pytest.importorskip("duckdb")
    from analytics_platform.backend.trade_log_db import TradeLogStore

    return TradeLogStore(tmp_path / "trade_log.duckdb")


def _make_client(tmp_path: Path):
    pytest.importorskip("duckdb")
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from analytics_platform.backend.app import create_app
    from analytics_platform.backend.config import Settings

    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    settings = Settings(
        repo_root=tmp_path,
        data_dir=data_dir,
        db_path=data_dir / "analytics.duckdb",
    )
    (tmp_path / "cache").mkdir(exist_ok=True)
    app = create_app(settings=settings)
    return TestClient(app)


# ── TradeLogStore unit tests ──────────────────────────────────


class TestTradeLogStore:
    def test_empty_list(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.list_trades() == []

    def test_create_and_list(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        trade = store.create({
            "entry_date": "2026-02-24",
            "symbol": "AAPL",
            "direction": "long",
            "entry_price": 150.0,
            "qty": 10,
            "stop_loss": 145.0,
        })
        assert trade["symbol"] == "AAPL"
        assert trade["status"] == "open"
        assert trade["risk_per_share"] == 5.0
        assert trade["r_multiple"] is None

        trades = store.list_trades()
        assert len(trades) == 1
        assert trades[0]["id"] == trade["id"]

    def test_close_long_trade(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        trade = store.create({
            "entry_date": "2026-02-24",
            "symbol": "MSFT",
            "direction": "long",
            "entry_price": 100.0,
            "qty": 5,
            "stop_loss": 95.0,
        })
        closed = store.update_exit(trade["id"], {"exit_price": 110.0})
        assert closed["status"] == "closed"
        assert closed["r_multiple"] == 2.0  # (110-100)/(100-95) = 2R
        assert closed["pnl_dollars"] == 50.0  # 10 * 5 shares

    def test_close_short_trade(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        trade = store.create({
            "entry_date": "2026-02-24",
            "symbol": "TSLA",
            "direction": "short",
            "entry_price": 200.0,
            "qty": 3,
            "stop_loss": 210.0,
        })
        closed = store.update_exit(trade["id"], {"exit_price": 180.0})
        assert closed["status"] == "closed"
        assert closed["r_multiple"] == 2.0  # (200-180)/(210-200) = 2R
        assert closed["pnl_dollars"] == 60.0  # 20 * 3 shares

    def test_delete(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        trade = store.create({
            "entry_date": "2026-02-24",
            "symbol": "GOOG",
            "entry_price": 100.0,
            "qty": 1,
            "stop_loss": 90.0,
        })
        assert store.delete(trade["id"]) is True
        assert store.list_trades() == []

    def test_delete_nonexistent(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        assert store.delete("no-such-id") is False

    def test_validation_zero_risk(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        with pytest.raises(ValueError, match="risk_per_share must be positive"):
            store.create({
                "entry_date": "2026-02-24",
                "symbol": "BAD",
                "entry_price": 100.0,
                "qty": 1,
                "stop_loss": 100.0,  # same as entry → zero risk
            })

    def test_summary_empty(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        s = store.get_summary()
        assert s["open_count"] == 0
        assert s["closed_count"] == 0
        assert s["win_rate"] is None
        assert s["total_pnl"] == 0.0

    def test_summary_with_trades(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        t1 = store.create({"entry_date": "2026-02-24", "symbol": "A", "entry_price": 100.0, "qty": 10, "stop_loss": 95.0})
        t2 = store.create({"entry_date": "2026-02-24", "symbol": "B", "entry_price": 50.0, "qty": 20, "stop_loss": 48.0})
        store.update_exit(t1["id"], {"exit_price": 110.0})  # win: +100
        store.update_exit(t2["id"], {"exit_price": 46.0})   # loss: -80

        s = store.get_summary()
        assert s["open_count"] == 0
        assert s["closed_count"] == 2
        assert s["wins"] == 1
        assert s["losses"] == 1
        assert s["win_rate"] == 50.0
        assert s["total_pnl"] == 20.0  # 100 - 80

    def test_filter_by_status(self, tmp_path: Path) -> None:
        store = _make_store(tmp_path)
        t1 = store.create({"entry_date": "2026-02-24", "symbol": "X", "entry_price": 100.0, "qty": 1, "stop_loss": 90.0})
        store.create({"entry_date": "2026-02-24", "symbol": "Y", "entry_price": 50.0, "qty": 1, "stop_loss": 45.0})
        store.update_exit(t1["id"], {"exit_price": 105.0})

        open_trades = store.list_trades(status="open")
        assert len(open_trades) == 1
        assert open_trades[0]["symbol"] == "Y"

        closed_trades = store.list_trades(status="closed")
        assert len(closed_trades) == 1
        assert closed_trades[0]["symbol"] == "X"


# ── API endpoint tests ────────────────────────────────────────


class TestTradeLogAPI:
    def test_list_empty(self, tmp_path: Path) -> None:
        client = _make_client(tmp_path)
        resp = client.get("/api/v1/trades/log")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["trades"] == []

    def test_create_and_list(self, tmp_path: Path) -> None:
        client = _make_client(tmp_path)
        resp = client.post("/api/v1/trades/log", json={
            "entry_date": "2026-02-24",
            "symbol": "aapl",
            "direction": "long",
            "entry_price": 150.0,
            "qty": 10,
            "stop_loss": 145.0,
        })
        assert resp.status_code == 200
        trade = resp.json()["data"]
        assert trade["symbol"] == "AAPL"

        resp2 = client.get("/api/v1/trades/log")
        assert len(resp2.json()["data"]["trades"]) == 1

    def test_close_trade(self, tmp_path: Path) -> None:
        client = _make_client(tmp_path)
        resp = client.post("/api/v1/trades/log", json={
            "entry_date": "2026-02-24",
            "symbol": "MSFT",
            "entry_price": 100.0,
            "qty": 5,
            "stop_loss": 95.0,
        })
        trade_id = resp.json()["data"]["id"]

        resp2 = client.put(f"/api/v1/trades/log/{trade_id}", json={
            "exit_price": 110.0,
            "exit_reason": "target",
        })
        assert resp2.status_code == 200
        assert resp2.json()["data"]["status"] == "closed"

    def test_delete_trade(self, tmp_path: Path) -> None:
        client = _make_client(tmp_path)
        resp = client.post("/api/v1/trades/log", json={
            "entry_date": "2026-02-24",
            "symbol": "GOOG",
            "entry_price": 100.0,
            "qty": 1,
            "stop_loss": 90.0,
        })
        trade_id = resp.json()["data"]["id"]

        resp2 = client.delete(f"/api/v1/trades/log/{trade_id}")
        assert resp2.status_code == 200

        resp3 = client.get("/api/v1/trades/log")
        assert len(resp3.json()["data"]["trades"]) == 0

    def test_summary(self, tmp_path: Path) -> None:
        client = _make_client(tmp_path)
        resp = client.get("/api/v1/trades/log/summary")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "open_count" in data
        assert "win_rate" in data
