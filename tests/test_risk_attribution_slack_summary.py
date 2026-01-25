from __future__ import annotations

import json
from pathlib import Path

import pytest

from analytics import risk_attribution_slack_summary as slack_summary


def _write_daily_summary(
    base_dir: Path,
    *,
    ny_date: str,
    baseline_total: float,
    modulated_total: float,
    delta_total: float,
    by_reason_code: dict[str, int],
    by_regime_code: dict[str, int],
    top_symbols: list[dict],
) -> Path:
    payload = {
        "schema_version": 1,
        "record_type": "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY",
        "date_ny": ny_date,
        "notional_totals": {
            "baseline_total": baseline_total,
            "modulated_total": modulated_total,
            "delta_total": delta_total,
        },
        "by_reason_code": by_reason_code,
        "by_regime_code": by_regime_code,
        "top_symbols_by_abs_delta_notional": top_symbols,
    }
    path = (
        base_dir
        / "PORTFOLIO_RISK_ATTRIBUTION_SUMMARY"
        / f"{ny_date}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def _write_rolling_summary(
    base_dir: Path,
    *,
    ny_date: str,
    window_label: str,
    by_reason_code: dict[str, dict[str, float | int]],
    top_symbols: list[dict],
) -> Path:
    payload = {
        "schema_version": 1,
        "record_type": "PORTFOLIO_RISK_ATTRIBUTION_ROLLING_SUMMARY",
        "as_of_date_ny": ny_date,
        "window": {"label": window_label},
        "breakdowns": {"by_reason_code": by_reason_code},
        "top_symbols": {"by_delta_notional": top_symbols},
    }
    path = (
        base_dir
        / "PORTFOLIO_RISK_ATTRIBUTION_ROLLING"
        / window_label
        / f"{ny_date}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return path


def test_feature_flag_off_no_send(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(slack_summary.FEATURE_FLAG_ENV, "0")
    called = {"count": 0}

    def _sender(*_args: object, **_kwargs: object) -> None:
        called["count"] += 1

    slack_summary.maybe_send_slack_summary(
        as_of="2024-01-05",
        ledger_root=tmp_path / "ledger",
        slack_sender=_sender,
    )
    assert called["count"] == 0


def test_missing_daily_summary_no_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(slack_summary.FEATURE_FLAG_ENV, "1")
    called = {"count": 0}

    def _sender(*_args: object, **_kwargs: object) -> None:
        called["count"] += 1

    slack_summary.maybe_send_slack_summary(
        as_of="2024-01-05",
        ledger_root=tmp_path / "ledger",
        slack_sender=_sender,
    )
    assert called["count"] == 0


def test_build_slack_summary_with_rolling(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledger"
    _write_daily_summary(
        ledger_root,
        ny_date="2024-01-05",
        baseline_total=100000.0,
        modulated_total=80000.0,
        delta_total=-20000.0,
        by_reason_code={"drawdown": 2, "risk_multiplier": 4},
        by_regime_code={"RISK_OFF": 3, "NEUTRAL": 1},
        top_symbols=[
            {"symbol": "AAPL", "abs_delta_notional": 12000.0, "delta_notional": -12000.0},
            {"symbol": "MSFT", "abs_delta_notional": 8000.0, "delta_notional": -8000.0},
        ],
    )
    _write_rolling_summary(
        ledger_root,
        ny_date="2024-01-05",
        window_label="20D",
        by_reason_code={
            "risk_multiplier": {"decisions": 10, "delta_notional": -15000.0},
            "drawdown": {"decisions": 5, "delta_notional": -5000.0},
        },
        top_symbols=[
            {"symbol": "TSLA", "delta_notional": -5000.0},
            {"symbol": "AAPL", "delta_notional": -12000.0},
            {"symbol": "MSFT", "delta_notional": -8000.0},
        ],
    )

    message = slack_summary.build_slack_summary(as_of="2024-01-05", ledger_root=ledger_root)
    assert message == (
        "Risk attribution summary (shadow) — 2024-01-05\n"
        "Exposure modulation (daily): baseline $100,000.00, modulated $80,000.00, "
        "delta -$20,000.00 (-0.2000).\n"
        "Dominant regime (daily): RISK_OFF (count 3).\n"
        "Dominant reason codes (20D): risk_multiplier (-$15,000.00), drawdown (-$5,000.00).\n"
        "Affected symbols (daily top list): 2.\n"
        "Top symbols (20D): AAPL (-$12,000.00), MSFT (-$8,000.00), TSLA (-$5,000.00)."
    )


def test_daily_fallback_ordering_and_counts(tmp_path: Path) -> None:
    ledger_root = tmp_path / "ledger"
    _write_daily_summary(
        ledger_root,
        ny_date="2024-02-01",
        baseline_total=1000.0,
        modulated_total=900.0,
        delta_total=-100.0,
        by_reason_code={"beta": 2, "alpha": 2},
        by_regime_code={"NEUTRAL": 1, "RISK_OFF": 1},
        top_symbols=[
            {"symbol": "ZZZ", "abs_delta_notional": 100.0, "delta_notional": -100.0},
            {"symbol": "AAA", "abs_delta_notional": 100.0, "delta_notional": -100.0},
        ],
    )

    message = slack_summary.build_slack_summary(as_of="2024-02-01", ledger_root=ledger_root)
    assert message is not None
    lines = message.splitlines()
    assert lines[2] == "Dominant regime (daily): NEUTRAL (count 1)."
    assert lines[3] == "Dominant reason codes (daily): alpha (count 2), beta (count 2)."
    assert lines[4] == "Affected symbols (daily top list): 2."
    assert lines[5] == "Top symbols (daily): AAA (-$100.00), ZZZ (-$100.00)."
