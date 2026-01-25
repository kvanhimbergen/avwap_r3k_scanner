from __future__ import annotations

import json
from pathlib import Path

import pytest

from analytics import risk_attribution_rolling


def _write_daily_summary(
    base_dir: Path,
    *,
    ny_date: str,
    baseline_total: float,
    delta_total: float,
    decisions_total: int = 2,
    decisions_modulated: int = 1,
    decisions_unmodified: int = 1,
    by_reason_code: dict | None = None,
    top_symbols: list[dict] | None = None,
) -> Path:
    payload = {
        "schema_version": 1,
        "record_type": "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY",
        "date_ny": ny_date,
        "notional_totals": {
            "baseline_total": baseline_total,
            "modulated_total": baseline_total + delta_total,
            "delta_total": delta_total,
        },
        "counts": {
            "events_total": decisions_total,
            "events_with_modulation": decisions_modulated,
            "events_no_modulation": decisions_unmodified,
        },
        "by_reason_code": by_reason_code or {},
        "top_symbols_by_abs_delta_notional": top_symbols or [],
    }
    path = base_dir / f"{ny_date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return path


def _make_dates(count: int) -> list[str]:
    return [f"2024-01-{day:02d}" for day in range(1, count + 1)]


def test_build_rolling_summary_window_and_totals(tmp_path: Path) -> None:
    input_dir = tmp_path / "ledger" / "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
    dates = _make_dates(21)
    for date_value in dates:
        day = int(date_value.split("-")[-1])
        _write_daily_summary(
            input_dir,
            ny_date=date_value,
            baseline_total=100.0 + day,
            delta_total=-10.0,
            by_reason_code={
                "RC1": {"decisions": 1, "delta_notional": -3.0},
                "RC2": {"decisions": 1, "delta_notional": -7.0},
            },
            top_symbols=[
                {"symbol": "AAA", "delta_notional": -2.0, "events": 1},
                {"symbol": "BBB", "delta_notional": -8.0, "events": 1},
            ],
        )

    summary = risk_attribution_rolling.build_rolling_summary(
        as_of_date_ny=dates[-1],
        input_dir=input_dir,
    )

    assert summary is not None
    assert summary["window"]["start_date_ny"] == dates[1]
    assert summary["window"]["end_date_ny"] == dates[-1]
    assert summary["window"]["dates_ny"] == dates[1:]

    expected_sources = [str(input_dir / f"{date_value}.json") for date_value in dates[1:]]
    assert summary["inputs"]["source_files"] == expected_sources

    expected_baseline = sum(100.0 + day for day in range(2, 22))
    expected_delta = -10.0 * 20
    expected_modulated = expected_baseline + expected_delta
    expected_delta_pct = round(expected_delta / expected_baseline, 4)

    assert summary["totals"] == {
        "baseline_notional": round(expected_baseline, 2),
        "modulated_notional": round(expected_modulated, 2),
        "delta_notional": round(expected_delta, 2),
        "delta_pct": expected_delta_pct,
        "decisions_total": 40,
        "decisions_modulated": 20,
        "decisions_unmodified": 20,
    }

    assert summary["breakdowns"]["by_reason_code"] == {
        "RC1": {"decisions": 20, "delta_notional": -60.0},
        "RC2": {"decisions": 20, "delta_notional": -140.0},
    }

    assert summary["top_symbols"]["by_delta_notional"] == [
        {"symbol": "BBB", "delta_notional": -160.0, "decisions": 20},
        {"symbol": "AAA", "delta_notional": -40.0, "decisions": 20},
    ]


def test_returns_none_when_window_incomplete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    input_dir = tmp_path / "ledger" / "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
    dates = _make_dates(5)
    for date_value in dates:
        _write_daily_summary(
            input_dir,
            ny_date=date_value,
            baseline_total=100.0,
            delta_total=-5.0,
        )

    summary = risk_attribution_rolling.build_rolling_summary(
        as_of_date_ny=dates[-1],
        input_dir=input_dir,
    )
    assert summary is None

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(risk_attribution_rolling.FEATURE_FLAG_ENV, "1")
    output = risk_attribution_rolling.generate_and_write_rolling_summary(
        as_of_date_ny=dates[-1],
    )
    assert output is None
    output_dir = tmp_path / "ledger" / "PORTFOLIO_RISK_ATTRIBUTION_ROLLING" / "20D"
    assert not output_dir.exists()


def test_delta_pct_null_when_baseline_zero(tmp_path: Path) -> None:
    input_dir = tmp_path / "ledger" / "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
    dates = _make_dates(20)
    for date_value in dates:
        _write_daily_summary(
            input_dir,
            ny_date=date_value,
            baseline_total=0.0,
            delta_total=-5.0,
        )

    summary = risk_attribution_rolling.build_rolling_summary(
        as_of_date_ny=dates[-1],
        input_dir=input_dir,
    )
    assert summary is not None
    assert summary["totals"]["baseline_notional"] == 0.0
    assert summary["totals"]["delta_pct"] is None


def test_top_symbols_sorted_and_capped(tmp_path: Path) -> None:
    input_dir = tmp_path / "ledger" / "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
    dates = _make_dates(20)
    symbols = [
        {"symbol": f"SYM{idx:02d}", "delta_notional": float(-idx), "events": 1}
        for idx in range(1, 31)
    ]
    for date_value in dates:
        _write_daily_summary(
            input_dir,
            ny_date=date_value,
            baseline_total=100.0,
            delta_total=-10.0,
            top_symbols=symbols,
        )

    summary = risk_attribution_rolling.build_rolling_summary(
        as_of_date_ny=dates[-1],
        input_dir=input_dir,
    )
    assert summary is not None
    top_symbols = summary["top_symbols"]["by_delta_notional"]
    assert len(top_symbols) == 25
    assert top_symbols[0] == {"symbol": "SYM30", "delta_notional": -600.0, "decisions": 20}
    assert top_symbols[-1] == {"symbol": "SYM06", "delta_notional": -120.0, "decisions": 20}


def test_write_rolling_summary_stable_json(tmp_path: Path) -> None:
    input_dir = tmp_path / "ledger" / "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
    dates = _make_dates(20)
    for date_value in dates:
        _write_daily_summary(
            input_dir,
            ny_date=date_value,
            baseline_total=100.0,
            delta_total=-10.0,
        )

    payload = risk_attribution_rolling.build_rolling_summary(
        as_of_date_ny=dates[-1],
        input_dir=input_dir,
    )
    assert payload is not None
    output_path = tmp_path / "rolling.json"
    risk_attribution_rolling.write_rolling_summary(payload, output_path)
    first_bytes = output_path.read_bytes()
    risk_attribution_rolling.write_rolling_summary(payload, output_path)
    second_bytes = output_path.read_bytes()
    assert first_bytes == second_bytes
