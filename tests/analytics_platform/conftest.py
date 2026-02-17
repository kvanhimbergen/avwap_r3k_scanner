from __future__ import annotations

import json
from pathlib import Path

import pytest

from analytics_platform.backend.config import Settings


@pytest.fixture()
def sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "ledger" / "PORTFOLIO_DECISIONS").mkdir(parents=True)
    (tmp_path / "ledger" / "STRATEGY_SIGNALS" / "S2_LETF_ORB_AGGRO").mkdir(parents=True)
    (tmp_path / "ledger" / "PORTFOLIO_RISK_CONTROLS").mkdir(parents=True)
    (tmp_path / "ledger" / "PORTFOLIO_THROTTLE").mkdir(parents=True)
    (tmp_path / "ledger" / "REGIME_E1").mkdir(parents=True)
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "backtests" / "suite_a" / "baseline").mkdir(parents=True)

    decision_record = {
        "schema_version": "1.0",
        "decision_id": "dec-001",
        "ts_utc": "2026-02-10T14:35:00+00:00",
        "ny_date": "2026-02-10",
        "mode": {"execution_mode": "SCHWAB_401K_MANUAL", "dry_run_forced": True},
        "gates": {
            "live_gate_applied": True,
            "market": {"is_open": True},
            "blocks": [{"code": "entry_delay_after_open", "message": "delay active"}],
        },
        "intents": {
            "intent_count": 2,
            "intents": [
                {"strategy_id": "S1_AVWAP_CORE", "symbol": "AAPL", "qty": 4, "side": "buy"},
                {"strategy_id": "S2_LETF_ORB_AGGRO", "symbol": "GOOGL", "qty": 3, "side": "buy"},
            ],
        },
        "intents_meta": {
            "entry_intents_created_count": 2,
            "entry_rejections": {
                "accepted": 2,
                "rejected": 1,
                "candidates_seen": 3,
                "reason_counts": {"boh_not_confirmed": 1},
                "rejected_symbols": [{"symbol": "MSFT", "reason": "boh_not_confirmed"}],
            }
        },
        "build": {"git_sha": "abc123"},
    }
    (tmp_path / "ledger" / "PORTFOLIO_DECISIONS" / "2026-02-10.jsonl").write_text(
        json.dumps(decision_record) + "\n", encoding="utf-8"
    )

    signal_record = {
        "record_type": "STRATEGY_SIGNAL",
        "strategy_id": "S2_LETF_ORB_AGGRO",
        "book_id": "SCHWAB_401K_MANUAL",
        "asof_date": "2026-02-10",
        "run_id": "run-001",
        "symbol": "GOOGL",
        "complex": "internet_platform",
        "eligible": True,
        "selected": True,
        "score": 0.22,
        "reason_codes": [],
        "gates": {"trend_ok": True},
        "metrics": {"ret_short": 0.12},
        "candidate": {"Symbol": "GOOGL"},
    }
    (tmp_path / "ledger" / "STRATEGY_SIGNALS" / "S2_LETF_ORB_AGGRO" / "2026-02-10.jsonl").write_text(
        json.dumps(signal_record) + "\n", encoding="utf-8"
    )

    risk_record = {
        "record_type": "PORTFOLIO_RISK_CONTROLS",
        "as_of_utc": "2026-02-10T14:35:00+00:00",
        "requested_ny_date": "2026-02-10",
        "resolved_ny_date": "2026-02-10",
        "risk_controls": {
            "risk_multiplier": 0.8,
            "max_positions": 5,
            "max_gross_exposure": 5000,
            "per_position_cap": 0.2,
            "throttle_reason": "risk_multiplier",
        },
    }
    (tmp_path / "ledger" / "PORTFOLIO_RISK_CONTROLS" / "2026-02-10.jsonl").write_text(
        json.dumps(risk_record) + "\n", encoding="utf-8"
    )

    throttle_record = {
        "record_type": "PORTFOLIO_THROTTLE",
        "as_of_utc": "2026-02-10T14:30:00+00:00",
        "requested_ny_date": "2026-02-10",
        "resolved_ny_date": "2026-02-10",
        "regime_id": "RISK_ON",
        "throttle": {"risk_multiplier": 1.0, "max_new_positions_multiplier": 1.0, "reasons": []},
    }
    (tmp_path / "ledger" / "PORTFOLIO_THROTTLE" / "2026-02-10.jsonl").write_text(
        json.dumps(throttle_record) + "\n", encoding="utf-8"
    )

    regime_record = {
        "record_type": "REGIME_E1",
        "as_of_utc": "2026-02-10T14:25:00+00:00",
        "requested_ny_date": "2026-02-10",
        "resolved_ny_date": "2026-02-10",
        "regime_id": "RISK_ON",
        "reason_codes": ["momentum"],
        "inputs_snapshot": {"spy": 0.2},
    }
    (tmp_path / "ledger" / "REGIME_E1" / "2026-02-10.jsonl").write_text(
        json.dumps(regime_record) + "\n", encoding="utf-8"
    )

    (tmp_path / "state" / "portfolio_decision_latest.json").write_text(
        json.dumps(decision_record), encoding="utf-8"
    )

    (tmp_path / "backtests" / "suite_a" / "baseline" / "summary.json").write_text(
        json.dumps({"cagr": 0.12, "max_drawdown": -0.08}), encoding="utf-8"
    )
    (tmp_path / "backtests" / "suite_a" / "baseline" / "equity_curve.csv").write_text(
        "date,equity\n2026-01-01,100000\n2026-01-02,100500\n",
        encoding="utf-8",
    )
    (tmp_path / "backtests" / "suite_a" / "baseline" / "trades.csv").write_text(
        "symbol,pnl\nAAPL,100\n", encoding="utf-8"
    )

    return tmp_path


@pytest.fixture()
def analytics_settings(sample_repo: Path) -> Settings:
    data_dir = sample_repo / "analytics_platform" / "data"
    return Settings(
        repo_root=sample_repo,
        data_dir=data_dir,
        db_path=data_dir / "analytics.duckdb",
        refresh_seconds=60,
        enable_scheduler=False,
    )
