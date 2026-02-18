from __future__ import annotations

import json
from pathlib import Path

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


def _post_fills(client, date="2026-02-17", fills=None, **kwargs):
    payload = {
        "date": date,
        "strategy_id": kwargs.get("strategy_id", "RAEC_401K_COORD"),
        "fees": kwargs.get("fees", 0.0),
        "notes": kwargs.get("notes", None),
        "fills": fills or [
            {"side": "BUY", "symbol": "XLI", "qty": 100, "price": 132.50},
            {"side": "SELL", "symbol": "BIL", "qty": 200, "price": 91.20},
        ],
    }
    return client.post("/api/v1/fills", json=payload)


# ── POST happy path ──────────────────────────────────────────────

def test_post_fills_happy_path(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = _post_fills(client)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["logged"] == 2
    assert data["skipped"] == 0
    assert len(data["records"]) == 2

    rec = data["records"][0]
    assert rec["symbol"] == "XLI"
    assert rec["side"] == "BUY"
    assert rec["qty"] == 100
    assert rec["price"] == 132.5
    assert "fill_id" in rec


# ── POST dedup ───────────────────────────────────────────────────

def test_post_fills_dedup(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp1 = _post_fills(client)
    assert resp1.status_code == 200
    assert resp1.json()["data"]["logged"] == 2

    resp2 = _post_fills(client)
    assert resp2.status_code == 200
    data2 = resp2.json()["data"]
    assert data2["logged"] == 0
    assert data2["skipped"] == 2


# ── POST validation: empty fills ─────────────────────────────────

def test_post_fills_validation_empty_fills(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.post("/api/v1/fills", json={
        "date": "2026-02-17",
        "fills": [],
    })
    assert resp.status_code == 422


# ── POST validation: missing date ────────────────────────────────

def test_post_fills_validation_missing_date(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.post("/api/v1/fills", json={
        "fills": [{"side": "BUY", "symbol": "XLI", "price": 100}],
    })
    assert resp.status_code == 422


# ── POST validation: bad side ────────────────────────────────────

def test_post_fills_validation_bad_side(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.post("/api/v1/fills", json={
        "date": "2026-02-17",
        "fills": [{"side": "HOLD", "symbol": "XLI", "price": 100}],
    })
    assert resp.status_code == 422


# ── POST options: strategy_id, fees, notes ───────────────────────

def test_post_fills_options(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = _post_fills(
        client,
        strategy_id="RAEC_401K_V3",
        fees=4.95,
        notes="morning session",
        fills=[{"side": "BUY", "symbol": "TQQQ", "qty": 50, "price": 65.00}],
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["logged"] == 1

    # Verify the ledger file has correct metadata
    ledger_path = analytics_settings.repo_root / "ledger" / "MANUAL_FILLS" / "2026-02-17.jsonl"
    assert ledger_path.exists()
    record = json.loads(ledger_path.read_text("utf-8").strip().splitlines()[0])
    assert record["strategy_id"] == "RAEC_401K_V3"
    assert record["fees"] == 4.95
    assert record["notes"] == "morning session"


# ── GET fills ────────────────────────────────────────────────────

def test_get_fills(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    # Post first so there's something to GET
    _post_fills(client)

    resp = client.get("/api/v1/fills?date=2026-02-17")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert len(data["records"]) == 2
    assert data["records"][0]["symbol"] in ("XLI", "BIL")


# ── GET fills empty ──────────────────────────────────────────────

def test_get_fills_empty(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = client.get("/api/v1/fills?date=2020-01-01")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["records"] == []


# ── POST fills with qty=None (price-only) ────────────────────────

def test_post_fills_price_only(analytics_settings) -> None:
    client = _make_client(analytics_settings)

    resp = _post_fills(
        client,
        fills=[{"side": "BUY", "symbol": "VTI", "price": 250.00}],
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["logged"] == 1
    assert data["records"][0]["qty"] is None
