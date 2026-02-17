from __future__ import annotations

import pytest

def test_build_readmodels_idempotent(analytics_settings) -> None:
    pytest.importorskip("duckdb")
    from analytics_platform.backend.db import connect_ro
    from analytics_platform.backend.readmodels.build_readmodels import build_readmodels

    first = build_readmodels(analytics_settings)
    second = build_readmodels(analytics_settings)

    assert first.data_version == second.data_version
    assert first.row_counts == second.row_counts

    with connect_ro(analytics_settings.db_path) as conn:
        decision_count = conn.execute("SELECT COUNT(*) FROM decision_cycles").fetchone()[0]
        signal_count = conn.execute("SELECT COUNT(*) FROM strategy_signals").fetchone()[0]
        backtest_count = conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]

    assert decision_count >= 1
    assert signal_count == 1
    assert backtest_count == 1
