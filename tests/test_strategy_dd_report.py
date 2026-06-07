from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from analytics.strategy_dd_report import (
    SubStrategyDDReport,
    _build_equity_curves,
    _summarize_curve,
    alert_if_breached,
    generate_report,
)
from data.prices import FixturePriceProvider


def _write_record(repo_root: Path, ny_date: str, sub_targets: dict[str, dict[str, float]]) -> None:
    ledger_dir = repo_root / "ledger" / "RAEC_REBALANCE" / "RAEC_401K_COORD"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    path = ledger_dir / f"{ny_date}.jsonl"
    record = {
        "record_type": "RAEC_COORDINATOR_RUN",
        "ny_date": ny_date,
        "sub_strategy_results": {
            key: {"regime": "RISK_ON", "targets": targets}
            for key, targets in sub_targets.items()
        },
    }
    with path.open("a") as fh:
        fh.write(json.dumps(record) + "\n")


def _linear_provider(
    symbol_to_start_end: dict[str, tuple[float, float]],
    days: list[date],
) -> FixturePriceProvider:
    series: dict[str, list[tuple[date, float]]] = {}
    for symbol, (start_price, end_price) in symbol_to_start_end.items():
        n = len(days)
        track = [start_price + (end_price - start_price) * i / max(n - 1, 1) for i in range(n)]
        series[symbol] = list(zip(days, track))
    return FixturePriceProvider(series)


# ---------------------------------------------------------------------------
# _summarize_curve
# ---------------------------------------------------------------------------

def test_summarize_flat_curve_has_no_drawdown() -> None:
    curve = [(date(2026, 1, 1), 1.0), (date(2026, 1, 2), 1.0), (date(2026, 1, 3), 1.0)]
    r = _summarize_curve("v3", curve)
    assert r.max_dd == 0.0
    assert r.current_dd == 0.0
    assert r.peak_equity == 1.0
    assert r.final_equity == 1.0


def test_summarize_simple_drawdown() -> None:
    # Peak at 1.20, trough at 0.96 → max dd = (0.96 / 1.20) - 1 = -0.20
    curve = [
        (date(2026, 1, 1), 1.00),
        (date(2026, 1, 2), 1.20),
        (date(2026, 1, 3), 0.96),
    ]
    r = _summarize_curve("v5", curve)
    assert r.peak_equity == 1.20
    assert r.max_dd == pytest.approx(-0.20)
    assert r.max_dd_date == date(2026, 1, 3)
    assert r.current_dd == pytest.approx(-0.20)


def test_summarize_recovers_to_no_current_dd() -> None:
    # Drawdown happens mid-period; final equity > peak so current_dd = 0,
    # max_dd captured.
    curve = [
        (date(2026, 1, 1), 1.00),
        (date(2026, 1, 2), 1.20),
        (date(2026, 1, 3), 0.96),
        (date(2026, 1, 4), 1.40),
    ]
    r = _summarize_curve("v5", curve)
    assert r.peak_equity == 1.40
    assert r.max_dd == pytest.approx(-0.20)
    assert r.current_dd == 0.0


# ---------------------------------------------------------------------------
# _build_equity_curves
# ---------------------------------------------------------------------------

def test_build_equity_curve_from_targets_and_prices() -> None:
    # V3 holds 100% SPY across two records spanning two trading days.
    # SPY goes 100 -> 110 -> 99 (down 10% from start, peak at day 2).
    days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    provider = _linear_provider({"SPY": (100.0, 99.0)}, days)
    # Make sure the middle day has the peak so we can see a drawdown.
    # Override the middle day price explicitly.
    series = list(provider._series["SPY"])
    series[1] = (days[1], 110.0)
    provider = FixturePriceProvider({"SPY": series})

    records = [
        {
            "record_type": "RAEC_COORDINATOR_RUN",
            "ny_date": d.isoformat(),
            "sub_strategy_results": {"v3": {"targets": {"SPY": 100.0}}},
        }
        for d in days
    ]
    curves = _build_equity_curves(records, provider)
    assert "v3" in curves
    eqs = [eq for _, eq in curves["v3"]]
    assert eqs[0] == 1.0
    assert eqs[1] == pytest.approx(1.10)  # 100% SPY × +10%
    assert eqs[2] == pytest.approx(1.10 * (99.0 / 110.0))  # × -10%


def test_build_equity_curve_handles_missing_price() -> None:
    # If a target symbol is missing from the provider, the remaining symbols
    # carry the day's return at renormalized weight.
    days = [date(2026, 1, 5), date(2026, 1, 6)]
    provider = FixturePriceProvider({
        "SPY": [(days[0], 100.0), (days[1], 110.0)],
        # GOLD missing entirely.
    })
    records = [
        {
            "record_type": "RAEC_COORDINATOR_RUN",
            "ny_date": d.isoformat(),
            "sub_strategy_results": {"v3": {"targets": {"SPY": 50.0, "GOLD": 50.0}}},
        }
        for d in days
    ]
    curves = _build_equity_curves(records, provider)
    eqs = [eq for _, eq in curves["v3"]]
    # SPY had +10% at 50% weight; renormalized to 1.0 because GOLD missing.
    # Expected return: +10% / (1 - 0.5) * 0.5 = +10%.
    assert eqs[-1] == pytest.approx(1.10)


# ---------------------------------------------------------------------------
# generate_report end-to-end
# ---------------------------------------------------------------------------

def test_generate_report_reads_ledger(tmp_path: Path) -> None:
    days = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    for d in days:
        _write_record(
            tmp_path,
            d.isoformat(),
            sub_targets={"v3": {"SPY": 100.0}, "v4": {"TLT": 100.0}},
        )
    provider = FixturePriceProvider({
        "SPY": [(days[0], 100.0), (days[1], 90.0), (days[2], 95.0)],  # -10%, +5.5%
        "TLT": [(days[0], 100.0), (days[1], 100.0), (days[2], 100.0)],  # flat
    })

    reports = generate_report(repo_root=tmp_path, provider=provider)

    by_key = {r.key: r for r in reports}
    assert set(by_key) == {"v3", "v4"}
    # v3 ended at 0.9 × 1.0556 ≈ 0.95
    assert by_key["v3"].final_equity == pytest.approx(0.95, abs=0.001)
    assert by_key["v3"].max_dd == pytest.approx(-0.10, abs=0.001)
    # v4 flat across the window
    assert by_key["v4"].final_equity == pytest.approx(1.0)
    assert by_key["v4"].max_dd == 0.0


# ---------------------------------------------------------------------------
# alert_if_breached
# ---------------------------------------------------------------------------

def test_alert_if_breached_posts_only_when_over_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[dict[str, Any]] = []

    def _capture(level: str, title: str, message: str, **kwargs: Any) -> None:
        posted.append({"level": level, "title": title, "message": message, **kwargs})

    import analytics.strategy_dd_report as report_module

    monkeypatch.setattr(report_module, "slack_alert", _capture)

    reports = [
        SubStrategyDDReport(key="v3", days=10, final_equity=0.85, peak_equity=1.0,
                            current_dd=-0.15, max_dd=-0.15, max_dd_date=date(2026, 3, 1)),
        SubStrategyDDReport(key="v4", days=10, final_equity=0.97, peak_equity=1.0,
                            current_dd=-0.03, max_dd=-0.03, max_dd_date=date(2026, 3, 1)),
    ]

    breached = alert_if_breached(reports, threshold=0.10)

    assert breached == 1
    assert len(posted) == 1
    assert "V3" in posted[0]["message"]
    assert "V4" not in posted[0]["message"]


def test_alert_if_breached_no_alert_when_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[dict[str, Any]] = []
    import analytics.strategy_dd_report as report_module
    monkeypatch.setattr(report_module, "slack_alert", lambda *a, **kw: posted.append({"a": a, "kw": kw}))

    reports = [
        SubStrategyDDReport(key="v3", days=10, final_equity=0.97, peak_equity=1.0,
                            current_dd=-0.03, max_dd=-0.03, max_dd_date=None),
    ]
    breached = alert_if_breached(reports, threshold=0.10)
    assert breached == 0
    assert posted == []
