from __future__ import annotations

import json

import pytest


def test_slippage_events_ingested(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute("SELECT * FROM execution_slippage").fetchall()
        cols = [d[0] for d in conn.description]

    assert len(rows) >= 3
    records = [dict(zip(cols, r)) for r in rows]
    aapl = [r for r in records if r["symbol"] == "AAPL" and r["strategy_id"] == "S1_AVWAP_CORE"]
    assert len(aapl) == 1
    assert abs(aapl[0]["slippage_bps"] - 3.78) < 0.01


def test_slippage_liquidity_buckets(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute("SELECT DISTINCT liquidity_bucket FROM execution_slippage").fetchall()

    buckets = {r[0] for r in rows}
    assert {"mega", "mid", "large"}.issubset(buckets)


def test_portfolio_snapshot_ingested(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute("SELECT * FROM portfolio_snapshots").fetchall()
        cols = [d[0] for d in conn.description]

    assert len(rows) >= 1
    row = dict(zip(cols, rows[0]))
    assert row["capital_total"] == 100000.0
    assert row["gross_exposure"] == 55000.0


def test_portfolio_positions_ingested(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute("SELECT * FROM portfolio_positions ORDER BY symbol").fetchall()
        cols = [d[0] for d in conn.description]

    assert len(rows) == 3
    records = [dict(zip(cols, r)) for r in rows]
    symbols = {r["symbol"] for r in records}
    assert symbols == {"AAPL", "MSFT", "TQQQ"}

    aapl = [r for r in records if r["symbol"] == "AAPL"][0]
    assert aapl["qty"] == 100
    assert aapl["mark_price"] == 185.50
    assert aapl["notional"] == 18550.0


def test_risk_attribution_ingested(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute("SELECT * FROM risk_attribution").fetchall()
        cols = [d[0] for d in conn.description]

    assert len(rows) >= 1
    row = dict(zip(cols, rows[0]))
    record = json.loads(row["record_json"])
    assert record["action"] == "SIZE_REDUCE"


def test_analytics_freshness_sources(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute(
            "SELECT source_name FROM freshness_health "
            "WHERE source_name IN ('execution_slippage', 'portfolio_snapshots')"
        ).fetchall()

    names = {r[0] for r in rows}
    assert "execution_slippage" in names
    assert "portfolio_snapshots" in names
