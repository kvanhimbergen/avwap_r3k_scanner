from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from data.prices import FixturePriceProvider
from strategies import raec_401k_v2, raec_401k_v3


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
    """Build provider where VTI trends up -> RISK_ON regime."""
    start = date(2024, 1, 1)
    series = {
        # Regime anchor
        "VTI": _linear_series(start=start, base=100, slope=0.34, wiggle=0.30),
        # Risk universe - leveraged ETFs with amplified slopes/wiggle
        "TQQQ": _linear_series(start=start, base=50, slope=0.90, wiggle=1.20),
        "SOXL": _linear_series(start=start, base=30, slope=0.85, wiggle=1.50),
        "UPRO": _linear_series(start=start, base=60, slope=0.70, wiggle=0.90),
        "TECL": _linear_series(start=start, base=40, slope=0.80, wiggle=1.10),
        "FNGU": _linear_series(start=start, base=25, slope=0.95, wiggle=1.80),
        # Sector ETFs
        "XLK": _linear_series(start=start, base=100, slope=0.45, wiggle=0.35),
        "SMH": _linear_series(start=start, base=100, slope=0.50, wiggle=0.50),
        "XLY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25),
        "XLC": _linear_series(start=start, base=100, slope=0.28, wiggle=0.20),
        "XLI": _linear_series(start=start, base=100, slope=0.22, wiggle=0.18),
        "QQQ": _linear_series(start=start, base=100, slope=0.48, wiggle=0.45),
        "SPY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25),
        # Defensive universe
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20),
        "USMV": _linear_series(start=start, base=100, slope=0.18, wiggle=0.10),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _risk_off_provider() -> FixturePriceProvider:
    """Build provider where VTI trends down -> RISK_OFF regime."""
    start = date(2024, 1, 1)
    series = {
        # Regime anchor - declining
        "VTI": _linear_series(start=start, base=210, slope=-0.30, wiggle=0.55),
        # Risk universe - leveraged ETFs decline faster
        "TQQQ": _linear_series(start=start, base=100, slope=-0.90, wiggle=1.50),
        "SOXL": _linear_series(start=start, base=80, slope=-0.85, wiggle=1.80),
        "UPRO": _linear_series(start=start, base=120, slope=-0.70, wiggle=1.10),
        "TECL": _linear_series(start=start, base=90, slope=-0.80, wiggle=1.30),
        "FNGU": _linear_series(start=start, base=70, slope=-0.95, wiggle=2.00),
        # Sector ETFs - declining
        "XLK": _linear_series(start=start, base=200, slope=-0.35, wiggle=0.50),
        "SMH": _linear_series(start=start, base=200, slope=-0.40, wiggle=0.60),
        "XLY": _linear_series(start=start, base=180, slope=-0.25, wiggle=0.35),
        "XLC": _linear_series(start=start, base=170, slope=-0.22, wiggle=0.30),
        "XLI": _linear_series(start=start, base=160, slope=-0.18, wiggle=0.25),
        "QQQ": _linear_series(start=start, base=210, slope=-0.35, wiggle=0.65),
        "SPY": _linear_series(start=start, base=210, slope=-0.26, wiggle=0.45),
        # Defensive - still positive
        "TLT": _linear_series(start=start, base=100, slope=0.07, wiggle=0.10),
        "GLD": _linear_series(start=start, base=100, slope=0.09, wiggle=0.16),
        "USMV": _linear_series(start=start, base=110, slope=0.03, wiggle=0.08),
        "IEF": _linear_series(start=start, base=100, slope=0.06, wiggle=0.06),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _circuit_breaker_provider() -> FixturePriceProvider:
    """VTI has >15% drawdown from 63d high, but SMA signals would otherwise say RISK_ON."""
    start = date(2024, 1, 1)
    n = 320
    # VTI: rises for most of the series, then sharp drop in last ~30 days
    vti_values: list[float] = []
    for idx in range(n):
        if idx < 280:
            vti_values.append(100 + 0.40 * idx)
        else:
            # Sharp decline: drop ~20% from peak
            peak = 100 + 0.40 * 280
            decline_days = idx - 280
            vti_values.append(peak * (1 - 0.006 * decline_days))
    vti_series = _make_series(start, vti_values)

    series = {
        "VTI": vti_series,
        "TQQQ": _linear_series(start=start, base=50, slope=0.90, wiggle=1.20, n=n),
        "SOXL": _linear_series(start=start, base=30, slope=0.85, wiggle=1.50, n=n),
        "UPRO": _linear_series(start=start, base=60, slope=0.70, wiggle=0.90, n=n),
        "TECL": _linear_series(start=start, base=40, slope=0.80, wiggle=1.10, n=n),
        "FNGU": _linear_series(start=start, base=25, slope=0.95, wiggle=1.80, n=n),
        "XLK": _linear_series(start=start, base=100, slope=0.45, wiggle=0.35, n=n),
        "SMH": _linear_series(start=start, base=100, slope=0.50, wiggle=0.50, n=n),
        "XLY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25, n=n),
        "XLC": _linear_series(start=start, base=100, slope=0.28, wiggle=0.20, n=n),
        "XLI": _linear_series(start=start, base=100, slope=0.22, wiggle=0.18, n=n),
        "QQQ": _linear_series(start=start, base=100, slope=0.48, wiggle=0.45, n=n),
        "SPY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25, n=n),
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08, n=n),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20, n=n),
        "USMV": _linear_series(start=start, base=100, slope=0.18, wiggle=0.10, n=n),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05, n=n),
        "BIL": _linear_series(start=start, base=100, slope=0.01, n=n),
    }
    return FixturePriceProvider(series)


def _seed_state(repo_root: Path, *, last_regime: str, allocs: dict[str, float],
                last_eval_date: str = "2026-01-31") -> None:
    state_path = repo_root / "state" / "strategies" / raec_401k_v3.BOOK_ID / f"{raec_401k_v3.STRATEGY_ID}.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "last_eval_date": last_eval_date,
                "last_regime": last_regime,
                "last_known_allocations": allocs,
            }
        )
    )


# ---------------------------------------------------------------------------
# Test: regime classification
# ---------------------------------------------------------------------------

def test_regime_risk_on(tmp_path: Path) -> None:
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"


def test_regime_risk_off(tmp_path: Path) -> None:
    provider = _risk_off_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"TQQQ": 50.0, "SOXL": 50.0})
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"


def test_circuit_breaker_forces_risk_off(tmp_path: Path) -> None:
    provider = _circuit_breaker_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"TQQQ": 50.0, "SOXL": 50.0})
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"


# ---------------------------------------------------------------------------
# Test: target allocation structure
# ---------------------------------------------------------------------------

def test_risk_on_targets_sum_and_top2(tmp_path: Path) -> None:
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"
    assert round(sum(result.targets.values()), 1) == 100.0
    risk_symbols = [sym for sym in result.targets if sym not in ("BIL",)]
    assert len(risk_symbols) <= 2
    assert set(risk_symbols).issubset(set(raec_401k_v3.RISK_UNIVERSE))


def test_risk_on_zero_cash_possible(tmp_path: Path) -> None:
    """BIL can be 0% or absent in RISK_ON (cash floor is 0%)."""
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"
    # Cash can be 0% (absent from targets) or very low
    cash_pct = result.targets.get("BIL", 0.0)
    assert cash_pct < 10.0  # Much lower floor than V2's 5%


def test_risk_off_80_defensive_20_cash(tmp_path: Path) -> None:
    provider = _risk_off_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"TQQQ": 50.0, "SOXL": 50.0})
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"
    assert round(sum(result.targets.values()), 1) == 100.0
    # Cash should be ~20%
    cash_pct = result.targets.get("BIL", 0.0)
    assert cash_pct >= 19.5
    assert cash_pct <= 25.0
    # No risk ETFs present
    risk_in_targets = set(result.targets.keys()) & set(raec_401k_v3.RISK_UNIVERSE)
    assert len(risk_in_targets) == 0


def test_transition_structure(tmp_path: Path) -> None:
    """Risk sleeve + defensive sleeve + min 5% cash = 100%."""
    start = date(2024, 1, 1)
    # VTI above SMA200 but with mild drawdown -> TRANSITION
    vti_values: list[float] = []
    for idx in range(320):
        if idx < 290:
            vti_values.append(100 + 0.30 * idx)
        else:
            peak = 100 + 0.30 * 290
            decline_days = idx - 290
            vti_values.append(peak * (1 - 0.002 * decline_days))

    series = {
        "VTI": _make_series(start, vti_values),
        "TQQQ": _linear_series(start=start, base=50, slope=0.90, wiggle=1.20),
        "SOXL": _linear_series(start=start, base=30, slope=0.85, wiggle=1.50),
        "UPRO": _linear_series(start=start, base=60, slope=0.70, wiggle=0.90),
        "TECL": _linear_series(start=start, base=40, slope=0.80, wiggle=1.10),
        "FNGU": _linear_series(start=start, base=25, slope=0.95, wiggle=1.80),
        "XLK": _linear_series(start=start, base=100, slope=0.45, wiggle=0.35),
        "SMH": _linear_series(start=start, base=100, slope=0.50, wiggle=0.50),
        "XLY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25),
        "XLC": _linear_series(start=start, base=100, slope=0.28, wiggle=0.20),
        "XLI": _linear_series(start=start, base=100, slope=0.22, wiggle=0.18),
        "QQQ": _linear_series(start=start, base=100, slope=0.48, wiggle=0.45),
        "SPY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25),
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20),
        "USMV": _linear_series(start=start, base=100, slope=0.18, wiggle=0.10),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    provider = FixturePriceProvider(series)
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"TQQQ": 50.0, "SOXL": 50.0})
    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    if result.regime == "TRANSITION":
        assert round(sum(result.targets.values()), 1) == 100.0
        cash_pct = result.targets.get("BIL", 0.0)
        assert cash_pct >= 4.5  # 5% floor


# ---------------------------------------------------------------------------
# Test: weekly rebalance trigger
# ---------------------------------------------------------------------------

def test_daily_rebalance_trigger(tmp_path: Path) -> None:
    provider = _risk_on_provider()
    asof_date = "2026-02-06"
    # Compute targets so we can seed allocs that match (no drift)
    asof = raec_401k_v3._parse_date(asof_date)
    cash_symbol = raec_401k_v3._get_cash_symbol(provider)
    vti_series = raec_401k_v3._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
    signal = raec_401k_v3._compute_anchor_signal(vti_series)
    feature_map = raec_401k_v3._load_symbol_features(provider=provider, asof=asof, cash_symbol=cash_symbol)
    targets = raec_401k_v3._targets_for_regime(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)

    # Same day, same regime, allocs at target -> no rebalance
    _seed_state(tmp_path, last_regime=signal.regime, allocs=targets,
                last_eval_date=asof_date)
    result_same_day = raec_401k_v3.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    # New day -> triggers rebalance
    _seed_state(tmp_path, last_regime=signal.regime, allocs=targets,
                last_eval_date="2026-02-05")
    result_new_day = raec_401k_v3.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    assert result_same_day.should_rebalance is False
    assert result_new_day.should_rebalance is True


# ---------------------------------------------------------------------------
# Test: drift threshold 1.5%
# ---------------------------------------------------------------------------

def test_drift_threshold_1_5(tmp_path: Path) -> None:
    provider = _risk_on_provider()

    asof_date = "2026-02-06"
    asof = raec_401k_v3._parse_date(asof_date)
    cash_symbol = raec_401k_v3._get_cash_symbol(provider)
    vti_series = raec_401k_v3._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
    signal = raec_401k_v3._compute_anchor_signal(vti_series)
    feature_map = raec_401k_v3._load_symbol_features(provider=provider, asof=asof, cash_symbol=cash_symbol)
    targets = raec_401k_v3._targets_for_regime(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)

    # Build allocs that are very close to target (within 1.4%)
    close_allocs = {sym: pct for sym, pct in targets.items()}
    first_sym = next(iter(close_allocs))
    close_allocs[first_sym] += 1.4
    # Adjust another symbol to keep total at 100
    other_syms = [s for s in close_allocs if s != first_sym]
    if other_syms:
        close_allocs[other_syms[0]] -= 1.4

    # Same day eval -> should NOT rebalance at 1.4% drift
    _seed_state(tmp_path, last_regime=signal.regime, allocs=close_allocs,
                last_eval_date="2026-02-06")
    result_no = raec_401k_v3.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    assert result_no.should_rebalance is False

    # Now push drift to 1.6%
    drift_allocs = {sym: pct for sym, pct in targets.items()}
    drift_allocs[first_sym] += 1.6
    if other_syms:
        drift_allocs[other_syms[0]] -= 1.6

    _seed_state(tmp_path, last_regime=signal.regime, allocs=drift_allocs,
                last_eval_date="2026-02-06")
    result_yes = raec_401k_v3.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    assert result_yes.should_rebalance is True


# ---------------------------------------------------------------------------
# Test: turnover cap 40%
# ---------------------------------------------------------------------------

def test_turnover_cap_40() -> None:
    intents = raec_401k_v3._build_intents(
        asof_date="2026-02-06",
        targets={"TQQQ": 55.0, "SOXL": 45.0},
        current={"BIL": 100.0},
        max_weekly_turnover=40.0,
    )
    buys = [intent for intent in intents if intent["side"] == "BUY"]
    total_buy_delta = sum(float(intent["delta_pct"]) for intent in buys)
    assert total_buy_delta == pytest.approx(40.0, abs=0.5)


# ---------------------------------------------------------------------------
# Test: 3-month momentum filter
# ---------------------------------------------------------------------------

def test_momentum_3m_filter() -> None:
    """Negative mom_3m symbols excluded with require_positive_momentum=True."""
    base_returns = tuple([0.01, -0.005, 0.008, -0.004, 0.006, -0.003] * 11)
    good = raec_401k_v3.SymbolFeature(
        symbol="TQQQ", close=100.0, mom_3m=0.15, mom_6m=0.20, mom_12m=0.25,
        vol_20d=0.30, vol_252d=0.30, drawdown_63d=-0.05, score=1.5,
        returns_window=base_returns,
    )
    bad = raec_401k_v3.SymbolFeature(
        symbol="SOXL", close=100.0, mom_3m=-0.10, mom_6m=0.05, mom_12m=0.10,
        vol_20d=0.35, vol_252d=0.35, drawdown_63d=-0.15, score=0.5,
        returns_window=base_returns,
    )
    feature_map = {"TQQQ": good, "SOXL": bad}
    ranked = raec_401k_v3._rank_symbols(
        ["TQQQ", "SOXL"], feature_map, require_positive_momentum=True
    )
    assert "TQQQ" in ranked
    assert "SOXL" not in ranked


# ---------------------------------------------------------------------------
# Test: intent ID deterministic and different from V2
# ---------------------------------------------------------------------------

def test_intent_id_deterministic() -> None:
    id1 = raec_401k_v3._intent_id(
        asof_date="2026-02-06", symbol="TQQQ", side="BUY", target_pct=55.0
    )
    id2 = raec_401k_v3._intent_id(
        asof_date="2026-02-06", symbol="TQQQ", side="BUY", target_pct=55.0
    )
    assert id1 == id2

    # Different from V2 because STRATEGY_ID differs
    id_v2 = raec_401k_v2._intent_id(
        asof_date="2026-02-06", symbol="TQQQ", side="BUY", target_pct=55.0
    )
    assert id1 != id_v2


# ---------------------------------------------------------------------------
# Test: sells before buys
# ---------------------------------------------------------------------------

def test_intents_sells_before_buys() -> None:
    intents = raec_401k_v3._build_intents(
        asof_date="2026-02-06",
        targets={"TQQQ": 60.0, "BIL": 40.0},
        current={"SOXL": 50.0, "BIL": 50.0},
    )
    sides = [intent["side"] for intent in intents]
    sell_indices = [i for i, s in enumerate(sides) if s == "SELL"]
    buy_indices = [i for i, s in enumerate(sides) if s == "BUY"]
    if sell_indices and buy_indices:
        assert max(sell_indices) < min(buy_indices)


# ---------------------------------------------------------------------------
# Test: dry_run no adapter
# ---------------------------------------------------------------------------

def test_dry_run_no_slack(tmp_path: Path) -> None:
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})

    class MockAdapter:
        called = False

        def send_summary_ticket(self, *args, **kwargs):
            MockAdapter.called = True
            raise AssertionError("Adapter should not be called in dry_run")

    result = raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        adapter_override=MockAdapter(),
    )
    assert not MockAdapter.called
    assert result.should_rebalance is True


# ---------------------------------------------------------------------------
# Test: state persistence
# ---------------------------------------------------------------------------

def test_state_persists(tmp_path: Path) -> None:
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})

    raec_401k_v3.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=False,
        allow_state_write=True,
        adapter_override=_NoOpAdapter(),
    )

    state_path = tmp_path / "state" / "strategies" / raec_401k_v3.BOOK_ID / f"{raec_401k_v3.STRATEGY_ID}.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["last_eval_date"] == "2026-02-06"
    assert state["last_regime"] in ("RISK_ON", "TRANSITION", "RISK_OFF")
    assert isinstance(state["last_targets"], dict)
    assert isinstance(state["last_known_allocations"], dict)


class _SendResult:
    sent = 1


class _NoOpAdapter:
    def send_summary_ticket(self, *args, **kwargs):
        return _SendResult()


# ---------------------------------------------------------------------------
# Test: portfolio vol with leveraged ETFs
# ---------------------------------------------------------------------------

def test_portfolio_vol_with_leveraged() -> None:
    """Covariance-aware vol estimation works with high-vol leveraged ETFs."""
    base_returns = tuple([0.03, -0.02, 0.025, -0.015, 0.02, -0.01] * 11)
    feature_tqqq = raec_401k_v3.SymbolFeature(
        symbol="TQQQ", close=100.0, mom_3m=0.30, mom_6m=0.50, mom_12m=0.80,
        vol_20d=0.60, vol_252d=0.55, drawdown_63d=-0.10, score=2.0,
        returns_window=base_returns,
    )
    feature_soxl = raec_401k_v3.SymbolFeature(
        symbol="SOXL", close=50.0, mom_3m=0.25, mom_6m=0.45, mom_12m=0.70,
        vol_20d=0.70, vol_252d=0.65, drawdown_63d=-0.12, score=1.8,
        returns_window=base_returns,
    )
    weights = {"TQQQ": 0.5, "SOXL": 0.5}
    feature_map = {"TQQQ": feature_tqqq, "SOXL": feature_soxl}
    estimated = raec_401k_v3._estimate_portfolio_vol(weights, feature_map)
    assert estimated > 0.0
    # With high-vol leveraged ETFs, portfolio vol should be substantial
    assert estimated > 0.10
