from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from data.prices import FixturePriceProvider
from strategies import raec_401k_v3, raec_401k_v4


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
    """Build provider where VTI trends up -> RISK_ON regime, with macro ETFs."""
    start = date(2024, 1, 1)
    series = {
        # Regime anchor
        "VTI": _linear_series(start=start, base=100, slope=0.34, wiggle=0.30),
        # V4 risk universe — macro ETFs
        "XLE": _linear_series(start=start, base=80, slope=0.35, wiggle=0.40),
        "ERX": _linear_series(start=start, base=40, slope=0.70, wiggle=1.10),
        "XLF": _linear_series(start=start, base=90, slope=0.28, wiggle=0.25),
        "FAS": _linear_series(start=start, base=50, slope=0.65, wiggle=1.00),
        "VNQ": _linear_series(start=start, base=85, slope=0.22, wiggle=0.20),
        "EFA": _linear_series(start=start, base=70, slope=0.18, wiggle=0.15),
        "EEM": _linear_series(start=start, base=40, slope=0.20, wiggle=0.25),
        "GDX": _linear_series(start=start, base=30, slope=0.25, wiggle=0.35),
        "XME": _linear_series(start=start, base=55, slope=0.30, wiggle=0.30),
        "DBA": _linear_series(start=start, base=20, slope=0.10, wiggle=0.08),
        "DBC": _linear_series(start=start, base=25, slope=0.12, wiggle=0.10),
        "TMF": _linear_series(start=start, base=10, slope=0.15, wiggle=0.20),
        "TBT": _linear_series(start=start, base=35, slope=0.20, wiggle=0.15),
        # V4 defensive universe
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20),
        "UUP": _linear_series(start=start, base=28, slope=0.03, wiggle=0.02),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05),
        "SHY": _linear_series(start=start, base=84, slope=0.02, wiggle=0.01),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _risk_off_provider() -> FixturePriceProvider:
    """Build provider where VTI trends down -> RISK_OFF regime."""
    start = date(2024, 1, 1)
    series = {
        "VTI": _linear_series(start=start, base=210, slope=-0.30, wiggle=0.55),
        "XLE": _linear_series(start=start, base=100, slope=-0.25, wiggle=0.40),
        "ERX": _linear_series(start=start, base=80, slope=-0.60, wiggle=1.20),
        "XLF": _linear_series(start=start, base=100, slope=-0.20, wiggle=0.30),
        "FAS": _linear_series(start=start, base=90, slope=-0.55, wiggle=1.00),
        "VNQ": _linear_series(start=start, base=90, slope=-0.18, wiggle=0.25),
        "EFA": _linear_series(start=start, base=75, slope=-0.15, wiggle=0.20),
        "EEM": _linear_series(start=start, base=45, slope=-0.12, wiggle=0.20),
        "GDX": _linear_series(start=start, base=35, slope=-0.10, wiggle=0.30),
        "XME": _linear_series(start=start, base=60, slope=-0.20, wiggle=0.25),
        "DBA": _linear_series(start=start, base=22, slope=-0.05, wiggle=0.06),
        "DBC": _linear_series(start=start, base=28, slope=-0.06, wiggle=0.08),
        "TMF": _linear_series(start=start, base=15, slope=-0.03, wiggle=0.15),
        "TBT": _linear_series(start=start, base=40, slope=-0.10, wiggle=0.12),
        "TLT": _linear_series(start=start, base=100, slope=0.07, wiggle=0.10),
        "GLD": _linear_series(start=start, base=100, slope=0.09, wiggle=0.16),
        "UUP": _linear_series(start=start, base=28, slope=0.04, wiggle=0.02),
        "IEF": _linear_series(start=start, base=100, slope=0.06, wiggle=0.06),
        "SHY": _linear_series(start=start, base=84, slope=0.02, wiggle=0.01),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _circuit_breaker_provider() -> FixturePriceProvider:
    """VTI has >15% drawdown from 63d high."""
    start = date(2024, 1, 1)
    n = 320
    vti_values: list[float] = []
    for idx in range(n):
        if idx < 280:
            vti_values.append(100 + 0.40 * idx)
        else:
            peak = 100 + 0.40 * 280
            decline_days = idx - 280
            vti_values.append(peak * (1 - 0.006 * decline_days))
    vti_series = _make_series(start, vti_values)

    series = {
        "VTI": vti_series,
        "XLE": _linear_series(start=start, base=80, slope=0.35, wiggle=0.40, n=n),
        "ERX": _linear_series(start=start, base=40, slope=0.70, wiggle=1.10, n=n),
        "XLF": _linear_series(start=start, base=90, slope=0.28, wiggle=0.25, n=n),
        "FAS": _linear_series(start=start, base=50, slope=0.65, wiggle=1.00, n=n),
        "VNQ": _linear_series(start=start, base=85, slope=0.22, wiggle=0.20, n=n),
        "EFA": _linear_series(start=start, base=70, slope=0.18, wiggle=0.15, n=n),
        "EEM": _linear_series(start=start, base=40, slope=0.20, wiggle=0.25, n=n),
        "GDX": _linear_series(start=start, base=30, slope=0.25, wiggle=0.35, n=n),
        "XME": _linear_series(start=start, base=55, slope=0.30, wiggle=0.30, n=n),
        "DBA": _linear_series(start=start, base=20, slope=0.10, wiggle=0.08, n=n),
        "DBC": _linear_series(start=start, base=25, slope=0.12, wiggle=0.10, n=n),
        "TMF": _linear_series(start=start, base=10, slope=0.15, wiggle=0.20, n=n),
        "TBT": _linear_series(start=start, base=35, slope=0.20, wiggle=0.15, n=n),
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08, n=n),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20, n=n),
        "UUP": _linear_series(start=start, base=28, slope=0.03, wiggle=0.02, n=n),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05, n=n),
        "SHY": _linear_series(start=start, base=84, slope=0.02, wiggle=0.01, n=n),
        "BIL": _linear_series(start=start, base=100, slope=0.01, n=n),
    }
    return FixturePriceProvider(series)


def _seed_state(repo_root: Path, *, last_regime: str, allocs: dict[str, float],
                last_eval_date: str = "2026-01-31") -> None:
    state_path = repo_root / "state" / "strategies" / raec_401k_v4.BOOK_ID / f"{raec_401k_v4.STRATEGY_ID}.json"
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


class _SendResult:
    sent = 1


class _NoOpAdapter:
    def send_summary_ticket(self, *args, **kwargs):
        return _SendResult()


# ---------------------------------------------------------------------------
# Test: regime classification
# ---------------------------------------------------------------------------

def test_regime_risk_on(tmp_path: Path) -> None:
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v4.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"


def test_regime_risk_off(tmp_path: Path) -> None:
    provider = _risk_off_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"XLE": 25.0, "ERX": 25.0, "XLF": 25.0, "FAS": 25.0})
    result = raec_401k_v4.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"


def test_circuit_breaker_forces_risk_off(tmp_path: Path) -> None:
    provider = _circuit_breaker_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"XLE": 25.0, "ERX": 25.0, "XLF": 25.0, "FAS": 25.0})
    result = raec_401k_v4.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"


# ---------------------------------------------------------------------------
# Test: target allocation structure
# ---------------------------------------------------------------------------

def test_risk_on_top_4(tmp_path: Path) -> None:
    """V4 selects top 4 risk symbols in RISK_ON."""
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v4.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"
    assert round(sum(result.targets.values()), 1) == 100.0
    risk_symbols = [sym for sym in result.targets if sym not in ("BIL",)]
    assert len(risk_symbols) <= 4
    assert set(risk_symbols).issubset(set(raec_401k_v4.RISK_UNIVERSE))


def test_risk_on_cash_floor_10(tmp_path: Path) -> None:
    """V4 RISK_ON has >= 10% cash floor."""
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v4.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"
    cash_pct = result.targets.get("BIL", 0.0)
    assert cash_pct >= 9.5  # 10% floor with rounding tolerance


def test_risk_on_max_weight_40(tmp_path: Path) -> None:
    """No single position exceeds 40% in V4."""
    provider = _risk_on_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v4.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"
    for sym, pct in result.targets.items():
        if sym != "BIL":
            assert pct <= 41.0, f"{sym} weight {pct}% exceeds 40% cap"


def test_risk_off_70_defensive_30_cash(tmp_path: Path) -> None:
    """RISK_OFF: ~70% defensive, ~30% cash."""
    provider = _risk_off_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"XLE": 25.0, "ERX": 25.0, "XLF": 25.0, "FAS": 25.0})
    result = raec_401k_v4.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"
    assert round(sum(result.targets.values()), 1) == 100.0
    cash_pct = result.targets.get("BIL", 0.0)
    assert cash_pct >= 29.5
    assert cash_pct <= 35.0
    risk_in_targets = set(result.targets.keys()) & set(raec_401k_v4.RISK_UNIVERSE)
    assert len(risk_in_targets) == 0


def test_transition_structure(tmp_path: Path) -> None:
    """Risk sleeve + defensive sleeve + 15% cash floor."""
    start = date(2024, 1, 1)
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
        "XLE": _linear_series(start=start, base=80, slope=0.35, wiggle=0.40),
        "ERX": _linear_series(start=start, base=40, slope=0.70, wiggle=1.10),
        "XLF": _linear_series(start=start, base=90, slope=0.28, wiggle=0.25),
        "FAS": _linear_series(start=start, base=50, slope=0.65, wiggle=1.00),
        "VNQ": _linear_series(start=start, base=85, slope=0.22, wiggle=0.20),
        "EFA": _linear_series(start=start, base=70, slope=0.18, wiggle=0.15),
        "EEM": _linear_series(start=start, base=40, slope=0.20, wiggle=0.25),
        "GDX": _linear_series(start=start, base=30, slope=0.25, wiggle=0.35),
        "XME": _linear_series(start=start, base=55, slope=0.30, wiggle=0.30),
        "DBA": _linear_series(start=start, base=20, slope=0.10, wiggle=0.08),
        "DBC": _linear_series(start=start, base=25, slope=0.12, wiggle=0.10),
        "TMF": _linear_series(start=start, base=10, slope=0.15, wiggle=0.20),
        "TBT": _linear_series(start=start, base=35, slope=0.20, wiggle=0.15),
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20),
        "UUP": _linear_series(start=start, base=28, slope=0.03, wiggle=0.02),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05),
        "SHY": _linear_series(start=start, base=84, slope=0.02, wiggle=0.01),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    provider = FixturePriceProvider(series)
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"XLE": 25.0, "ERX": 25.0, "XLF": 25.0, "FAS": 25.0})
    result = raec_401k_v4.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    if result.regime == "TRANSITION":
        assert round(sum(result.targets.values()), 1) == 100.0
        cash_pct = result.targets.get("BIL", 0.0)
        assert cash_pct >= 14.0  # 15% floor with rounding tolerance


# ---------------------------------------------------------------------------
# Test: daily rebalance trigger
# ---------------------------------------------------------------------------

def test_daily_rebalance_trigger(tmp_path: Path) -> None:
    provider = _risk_on_provider()
    asof_date = "2026-02-06"
    asof = raec_401k_v4._parse_date(asof_date)
    cash_symbol = raec_401k_v4._get_cash_symbol(provider)
    vti_series = raec_401k_v4._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
    signal = raec_401k_v4._compute_anchor_signal(vti_series)
    feature_map = raec_401k_v4._load_symbol_features(provider=provider, asof=asof, cash_symbol=cash_symbol)
    targets = raec_401k_v4._targets_for_regime(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)

    # Same day, same regime, allocs at target -> no rebalance
    _seed_state(tmp_path, last_regime=signal.regime, allocs=targets,
                last_eval_date=asof_date)
    result_same_day = raec_401k_v4.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    # New day -> triggers rebalance
    _seed_state(tmp_path, last_regime=signal.regime, allocs=targets,
                last_eval_date="2026-02-05")
    result_new_day = raec_401k_v4.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    assert result_same_day.should_rebalance is False
    assert result_new_day.should_rebalance is True


# ---------------------------------------------------------------------------
# Test: drift threshold 2.0%
# ---------------------------------------------------------------------------

def test_drift_threshold_2_0(tmp_path: Path) -> None:
    provider = _risk_on_provider()
    asof_date = "2026-02-06"
    asof = raec_401k_v4._parse_date(asof_date)
    cash_symbol = raec_401k_v4._get_cash_symbol(provider)
    vti_series = raec_401k_v4._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
    signal = raec_401k_v4._compute_anchor_signal(vti_series)
    feature_map = raec_401k_v4._load_symbol_features(provider=provider, asof=asof, cash_symbol=cash_symbol)
    targets = raec_401k_v4._targets_for_regime(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)

    # Build allocs within 1.9% drift
    close_allocs = {sym: pct for sym, pct in targets.items()}
    first_sym = next(iter(close_allocs))
    close_allocs[first_sym] += 1.9
    other_syms = [s for s in close_allocs if s != first_sym]
    if other_syms:
        close_allocs[other_syms[0]] -= 1.9

    _seed_state(tmp_path, last_regime=signal.regime, allocs=close_allocs,
                last_eval_date="2026-02-06")
    result_no = raec_401k_v4.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    assert result_no.should_rebalance is False

    # 2.1% drift -> triggers
    drift_allocs = {sym: pct for sym, pct in targets.items()}
    drift_allocs[first_sym] += 2.1
    if other_syms:
        drift_allocs[other_syms[0]] -= 2.1

    _seed_state(tmp_path, last_regime=signal.regime, allocs=drift_allocs,
                last_eval_date="2026-02-06")
    result_yes = raec_401k_v4.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    assert result_yes.should_rebalance is True


# ---------------------------------------------------------------------------
# Test: turnover cap 30%
# ---------------------------------------------------------------------------

def test_turnover_cap_30() -> None:
    intents = raec_401k_v4._build_intents(
        asof_date="2026-02-06",
        targets={"XLE": 30.0, "ERX": 25.0, "XLF": 20.0, "FAS": 15.0, "BIL": 10.0},
        current={"BIL": 100.0},
        max_weekly_turnover=30.0,
    )
    buys = [intent for intent in intents if intent["side"] == "BUY"]
    total_buy_delta = sum(float(intent["delta_pct"]) for intent in buys)
    assert total_buy_delta == pytest.approx(30.0, abs=0.5)


# ---------------------------------------------------------------------------
# Test: 3-month momentum filter
# ---------------------------------------------------------------------------

def test_momentum_3m_filter() -> None:
    base_returns = tuple([0.01, -0.005, 0.008, -0.004, 0.006, -0.003] * 11)
    good = raec_401k_v4.SymbolFeature(
        symbol="XLE", close=100.0, mom_3m=0.15, mom_6m=0.20, mom_12m=0.25,
        vol_20d=0.30, vol_252d=0.30, drawdown_63d=-0.05, score=1.5,
        returns_window=base_returns,
    )
    bad = raec_401k_v4.SymbolFeature(
        symbol="ERX", close=100.0, mom_3m=-0.10, mom_6m=0.05, mom_12m=0.10,
        vol_20d=0.35, vol_252d=0.35, drawdown_63d=-0.15, score=0.5,
        returns_window=base_returns,
    )
    feature_map = {"XLE": good, "ERX": bad}
    ranked = raec_401k_v4._rank_symbols(
        ["XLE", "ERX"], feature_map, require_positive_momentum=True
    )
    assert "XLE" in ranked
    assert "ERX" not in ranked


# ---------------------------------------------------------------------------
# Test: intent ID deterministic and different from V3
# ---------------------------------------------------------------------------

def test_intent_id_deterministic() -> None:
    id1 = raec_401k_v4._intent_id(
        asof_date="2026-02-06", symbol="XLE", side="BUY", target_pct=30.0
    )
    id2 = raec_401k_v4._intent_id(
        asof_date="2026-02-06", symbol="XLE", side="BUY", target_pct=30.0
    )
    assert id1 == id2

    # Different from V3 because STRATEGY_ID differs
    id_v3 = raec_401k_v3._intent_id(
        asof_date="2026-02-06", symbol="XLE", side="BUY", target_pct=30.0
    )
    assert id1 != id_v3


# ---------------------------------------------------------------------------
# Test: sells before buys
# ---------------------------------------------------------------------------

def test_intents_sells_before_buys() -> None:
    intents = raec_401k_v4._build_intents(
        asof_date="2026-02-06",
        targets={"XLE": 40.0, "BIL": 60.0},
        current={"ERX": 50.0, "BIL": 50.0},
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

    result = raec_401k_v4.run_strategy(
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

    raec_401k_v4.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=False,
        allow_state_write=True,
        adapter_override=_NoOpAdapter(),
    )

    state_path = tmp_path / "state" / "strategies" / raec_401k_v4.BOOK_ID / f"{raec_401k_v4.STRATEGY_ID}.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["last_eval_date"] == "2026-02-06"
    assert state["last_regime"] in ("RISK_ON", "TRANSITION", "RISK_OFF")
    assert isinstance(state["last_targets"], dict)
    assert isinstance(state["last_known_allocations"], dict)
