from __future__ import annotations

import json

import pytest


def test_raec_rebalance_event_ingested(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute("SELECT * FROM raec_rebalance_events").fetchall()
        cols = [d[0] for d in conn.description]

    assert len(rows) >= 1
    row = dict(zip(cols, rows[0]))
    assert row["strategy_id"] == "RAEC_401K_V3"
    assert row["regime"] == "RISK_ON"
    assert row["should_rebalance"] is True


def test_raec_allocations_target_and_current(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute("SELECT * FROM raec_allocations").fetchall()
        cols = [d[0] for d in conn.description]

    allocs = [dict(zip(cols, r)) for r in rows]

    targets = {a["symbol"]: a["weight_pct"] for a in allocs if a["alloc_type"] == "target"}
    assert targets["TQQQ"] == 35.0
    assert targets["SOXL"] == 25.0
    assert targets["BIL"] == 40.0

    currents = {a["symbol"]: a["weight_pct"] for a in allocs if a["alloc_type"] == "current"}
    assert currents["SPY"] == 50.0
    assert currents["BIL"] == 50.0


def test_raec_intents_parsed(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM raec_intents WHERE strategy_id = 'RAEC_401K_V3'"
        ).fetchall()
        cols = [d[0] for d in conn.description]

    assert len(rows) == 3
    intents = [dict(zip(cols, r)) for r in rows]
    tqqq = [i for i in intents if i["symbol"] == "TQQQ"]
    assert len(tqqq) == 1
    assert tqqq[0]["side"] == "BUY"
    assert tqqq[0]["delta_pct"] == 35.0


def test_raec_coordinator_run_ingested(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute("SELECT * FROM raec_coordinator_runs").fetchall()
        cols = [d[0] for d in conn.description]

    assert len(rows) >= 1
    row = dict(zip(cols, rows[0]))
    capital_split = json.loads(row["capital_split_json"])
    assert capital_split["v3"] == 0.40


def test_raec_freshness_source_exists(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    build_readmodels(analytics_settings)

    with connect_ro(analytics_settings.db_path) as conn:
        rows = conn.execute(
            "SELECT source_name FROM freshness_health WHERE source_name = 'raec_rebalance_events'"
        ).fetchall()

    assert len(rows) == 1
    assert rows[0][0] == "raec_rebalance_events"


def test_raec_ingestion_idempotent(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    first = build_readmodels(analytics_settings)
    second = build_readmodels(analytics_settings)

    assert first.data_version == second.data_version
    assert first.row_counts == second.row_counts
