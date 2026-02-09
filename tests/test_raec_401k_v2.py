from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from data.prices import FixturePriceProvider
from strategies import raec_401k_v2


def _make_series(start: date, values: list[float]) -> list[tuple[date, float]]:
    return [(start + timedelta(days=idx), value) for idx, value in enumerate(values)]


def _linear_series(
    *,
    start: date,
    base: float,
    slope: float,
    wiggle: float = 0.0,
    n: int = 320,
) -> list[tuple[date, float]]:
    values: list[float] = []
    for idx in range(n):
        value = base + (slope * idx)
        if wiggle:
            value += wiggle if idx % 2 == 0 else -wiggle
        values.append(max(1.0, value))
    return _make_series(start, values)


def _risk_on_provider() -> FixturePriceProvider:
    start = date(2024, 1, 1)
    series = {
        "VTI": _linear_series(start=start, base=100, slope=0.34, wiggle=0.30),
        "QQQ": _linear_series(start=start, base=100, slope=0.48, wiggle=0.45),
        "SPY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25),
        "IWM": _linear_series(start=start, base=100, slope=0.12, wiggle=0.55),
        "QUAL": _linear_series(start=start, base=100, slope=0.39, wiggle=0.20),
        "MTUM": _linear_series(start=start, base=100, slope=0.44, wiggle=0.40),
        "VTV": _linear_series(start=start, base=100, slope=0.21, wiggle=0.15),
        "VEA": _linear_series(start=start, base=100, slope=0.14, wiggle=0.18),
        "VWO": _linear_series(start=start, base=100, slope=0.10, wiggle=0.22),
        "USMV": _linear_series(start=start, base=100, slope=0.18, wiggle=0.10),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05),
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _risk_off_provider() -> FixturePriceProvider:
    start = date(2024, 1, 1)
    series = {
        "VTI": _linear_series(start=start, base=210, slope=-0.30, wiggle=0.55),
        "QQQ": _linear_series(start=start, base=210, slope=-0.35, wiggle=0.65),
        "SPY": _linear_series(start=start, base=210, slope=-0.26, wiggle=0.45),
        "IWM": _linear_series(start=start, base=200, slope=-0.28, wiggle=0.50),
        "QUAL": _linear_series(start=start, base=180, slope=-0.18, wiggle=0.35),
        "MTUM": _linear_series(start=start, base=200, slope=-0.32, wiggle=0.60),
        "VTV": _linear_series(start=start, base=170, slope=-0.14, wiggle=0.20),
        "VEA": _linear_series(start=start, base=150, slope=-0.10, wiggle=0.15),
        "VWO": _linear_series(start=start, base=140, slope=-0.12, wiggle=0.18),
        "USMV": _linear_series(start=start, base=110, slope=0.03, wiggle=0.08),
        "IEF": _linear_series(start=start, base=100, slope=0.06, wiggle=0.06),
        "TLT": _linear_series(start=start, base=100, slope=0.07, wiggle=0.10),
        "GLD": _linear_series(start=start, base=100, slope=0.09, wiggle=0.16),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _seed_state(repo_root: Path, *, last_regime: str, allocs: dict[str, float]) -> None:
    state_path = repo_root / "state" / "strategies" / raec_401k_v2.BOOK_ID / f"{raec_401k_v2.STRATEGY_ID}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_eval_date": "2026-01-31",
                "last_regime": last_regime,
                "last_known_allocations": allocs,
            }
        )
    )


def test_run_strategy_risk_on_targets_dynamic(tmp_path: Path) -> None:
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})

    result = raec_401k_v2.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )

    assert result.regime == "RISK_ON"
    assert round(sum(result.targets.values()), 1) == 100.0
    assert "BIL" in result.targets
    assert result.targets["BIL"] >= 4.5
    risk_symbols = [symbol for symbol in result.targets if symbol != "BIL"]
    assert len(risk_symbols) <= 3
    assert set(risk_symbols).issubset(set(raec_401k_v2.RISK_UNIVERSE))


def test_run_strategy_risk_off_keeps_cash_buffer(tmp_path: Path) -> None:
    provider = _risk_off_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"QQQ": 30.0, "MTUM": 30.0, "BIL": 40.0})

    result = raec_401k_v2.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )

    assert result.regime == "RISK_OFF"
    assert round(sum(result.targets.values()), 1) == 100.0
    assert result.targets.get("BIL", 0.0) >= 40.0
    assert result.should_rebalance


def test_turnover_cap_limits_buys() -> None:
    intents = raec_401k_v2._build_intents(
        asof_date="2026-02-06",
        targets={"QQQ": 45.0, "MTUM": 30.0, "QUAL": 20.0, "BIL": 5.0},
        current={"BIL": 100.0},
        max_weekly_turnover=15.0,
    )
    buys = [intent for intent in intents if intent["side"] == "BUY"]
    total_buy_delta = sum(float(intent["delta_pct"]) for intent in buys)
    assert total_buy_delta == pytest.approx(15.0, abs=0.2)


def test_portfolio_vol_estimator_accounts_for_covariance() -> None:
    base_returns = tuple([0.01, -0.005, 0.008, -0.004, 0.006, -0.003] * 11)
    feature_a = raec_401k_v2.SymbolFeature(
        symbol="AAA",
        close=100.0,
        mom_6m=0.1,
        mom_12m=0.2,
        vol_20d=0.2,
        vol_252d=0.2,
        drawdown_63d=-0.05,
        score=1.0,
        returns_window=base_returns,
    )
    feature_b = raec_401k_v2.SymbolFeature(
        symbol="BBB",
        close=100.0,
        mom_6m=0.1,
        mom_12m=0.2,
        vol_20d=0.2,
        vol_252d=0.2,
        drawdown_63d=-0.05,
        score=1.0,
        returns_window=base_returns,
    )
    weights = {"AAA": 0.5, "BBB": 0.5}
    feature_map = {"AAA": feature_a, "BBB": feature_b}

    estimated = raec_401k_v2._estimate_portfolio_vol(weights, feature_map)
    sigma = raec_401k_v2._compute_volatility(list(base_returns))
    diagonal_only = ((0.5 * sigma) ** 2 + (0.5 * sigma) ** 2) ** 0.5
    assert estimated > diagonal_only
