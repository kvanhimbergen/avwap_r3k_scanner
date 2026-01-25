from __future__ import annotations

import json
from pathlib import Path

from analytics import risk_attribution_summary


def _sample_events() -> list[dict]:
    return [
        {
            "date_ny": "2024-01-02",
            "symbol": "AAPL",
            "baseline": {"qty": 10, "notional": 1000.0},
            "modulated": {"qty": 8, "notional": 800.0},
            "delta": {"qty": -2, "notional": -200.0, "pct_notional": -0.2},
            "reason_codes": ["risk_multiplier", "drawdown"],
            "regime": {"code": "RISK_OFF"},
            "hard_caps_applied": ["risk_multiplier"],
        },
        {
            "date_ny": "2024-01-02",
            "symbol": "MSFT",
            "baseline": {"qty": 5, "notional": 500.0},
            "modulated": {"qty": 6, "notional": 600.0},
            "delta": {"qty": 1, "notional": 100.0, "pct_notional": 0.2},
            "reason_codes": ["risk_multiplier"],
            "regime": {"code": None},
            "hard_caps_applied": ["max_gross_exposure"],
        },
        {
            "date_ny": "2024-01-02",
            "symbol": "AAPL",
            "baseline": {"qty": 2, "notional": 200.0},
            "modulated": {"qty": 2, "notional": 200.0},
            "delta": {"qty": 0, "notional": 0.0, "pct_notional": 0.0},
            "reason_codes": [],
            "regime": {"code": None},
            "hard_caps_applied": [],
        },
    ]


def test_build_daily_summary_deterministic() -> None:
    events = _sample_events()
    summary = risk_attribution_summary.build_daily_summary(
        ny_date="2024-01-02",
        events=events,
        source="unit_test",
    )

    assert summary["schema_version"] == 1
    assert summary["record_type"] == "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
    assert summary["date_ny"] == "2024-01-02"
    assert summary["source"] == "unit_test"

    assert summary["counts"] == {
        "events_total": 3,
        "events_with_modulation": 2,
        "events_no_modulation": 1,
    }

    assert summary["notional_totals"] == {
        "baseline_total": 1700.0,
        "modulated_total": 1600.0,
        "delta_total": -100.0,
        "delta_total_abs": 100.0,
    }

    assert summary["delta_pct_distribution"] == {
        "min": -0.2,
        "median": 0.0,
        "max": 0.2,
    }

    assert summary["by_reason_code"] == {
        "drawdown": 1,
        "risk_multiplier": 2,
    }

    assert summary["by_regime_code"] == {
        "RISK_OFF": 1,
        "UNKNOWN": 2,
    }

    assert summary["hard_caps_applied_counts"] == {
        "max_gross_exposure": 1,
        "risk_multiplier": 1,
    }

    assert summary["top_symbols_by_abs_delta_notional"] == [
        {
            "symbol": "AAPL",
            "abs_delta_notional": 200.0,
            "delta_notional": -200.0,
            "baseline_notional": 1200.0,
            "modulated_notional": 1000.0,
            "events": 2,
        },
        {
            "symbol": "MSFT",
            "abs_delta_notional": 100.0,
            "delta_notional": 100.0,
            "baseline_notional": 500.0,
            "modulated_notional": 600.0,
            "events": 1,
        },
    ]


def test_write_daily_summary_stable_json(tmp_path: Path) -> None:
    summary = risk_attribution_summary.build_daily_summary(
        ny_date="2024-01-02",
        events=_sample_events(),
        source="unit_test",
    )
    output_path = risk_attribution_summary.write_daily_summary(
        summary,
        base_dir=str(tmp_path),
    )
    content = output_path.read_text(encoding="utf-8")
    expected = json.dumps(
        summary,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert content == f"{expected}\n"


def test_missing_input_file_returns_empty(tmp_path: Path) -> None:
    events = risk_attribution_summary.load_attribution_events(
        ny_date="2024-01-03",
        base_dir=str(tmp_path),
    )
    assert events == []
    summary = risk_attribution_summary.build_daily_summary(
        ny_date="2024-01-03",
        events=events,
        source="unit_test",
    )
    assert summary["counts"]["events_total"] == 0
