from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from data.prices import FixturePriceProvider
from strategies import raec_401k_v3, raec_401k_v4, raec_401k_v5


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


def _both_up_provider() -> FixturePriceProvider:
    """VTI and QQQ both trend up -> RISK_ON."""
    start = date(2024, 1, 1)
    series = {
        "VTI": _linear_series(start=start, base=100, slope=0.34, wiggle=0.30),
        "QQQ": _linear_series(start=start, base=100, slope=0.48, wiggle=0.45),
        # V5 risk universe
        "SOXL": _linear_series(start=start, base=30, slope=0.85, wiggle=1.50),
        "TECL": _linear_series(start=start, base=40, slope=0.80, wiggle=1.10),
        "FNGU": _linear_series(start=start, base=25, slope=0.95, wiggle=1.80),
        "NVDL": _linear_series(start=start, base=35, slope=0.90, wiggle=1.40),
        "SMH": _linear_series(start=start, base=100, slope=0.50, wiggle=0.50),
        "IGV": _linear_series(start=start, base=80, slope=0.35, wiggle=0.30),
        "BOTZ": _linear_series(start=start, base=25, slope=0.20, wiggle=0.15),
        "WCLD": _linear_series(start=start, base=20, slope=0.15, wiggle=0.12),
        "HACK": _linear_series(start=start, base=50, slope=0.25, wiggle=0.20),
        "ARKK": _linear_series(start=start, base=40, slope=0.30, wiggle=0.35),
        # Individual stocks
        "NVDA": _linear_series(start=start, base=500, slope=2.50, wiggle=3.00),
        "AMD": _linear_series(start=start, base=120, slope=0.60, wiggle=0.80),
        "AVGO": _linear_series(start=start, base=150, slope=0.80, wiggle=1.00),
        "MSFT": _linear_series(start=start, base=350, slope=0.90, wiggle=1.20),
        "GOOGL": _linear_series(start=start, base=140, slope=0.45, wiggle=0.50),
        # Defensive
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20),
        "USMV": _linear_series(start=start, base=100, slope=0.18, wiggle=0.10),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _vti_down_provider() -> FixturePriceProvider:
    """VTI trends down, QQQ trends up -> RISK_OFF (most conservative wins)."""
    start = date(2024, 1, 1)
    series = {
        "VTI": _linear_series(start=start, base=210, slope=-0.30, wiggle=0.55),
        "QQQ": _linear_series(start=start, base=100, slope=0.48, wiggle=0.45),
        "SOXL": _linear_series(start=start, base=30, slope=0.85, wiggle=1.50),
        "TECL": _linear_series(start=start, base=40, slope=0.80, wiggle=1.10),
        "FNGU": _linear_series(start=start, base=25, slope=0.95, wiggle=1.80),
        "NVDL": _linear_series(start=start, base=35, slope=0.90, wiggle=1.40),
        "SMH": _linear_series(start=start, base=100, slope=0.50, wiggle=0.50),
        "IGV": _linear_series(start=start, base=80, slope=0.35, wiggle=0.30),
        "BOTZ": _linear_series(start=start, base=25, slope=0.20, wiggle=0.15),
        "WCLD": _linear_series(start=start, base=20, slope=0.15, wiggle=0.12),
        "HACK": _linear_series(start=start, base=50, slope=0.25, wiggle=0.20),
        "ARKK": _linear_series(start=start, base=40, slope=0.30, wiggle=0.35),
        "NVDA": _linear_series(start=start, base=500, slope=2.50, wiggle=3.00),
        "AMD": _linear_series(start=start, base=120, slope=0.60, wiggle=0.80),
        "AVGO": _linear_series(start=start, base=150, slope=0.80, wiggle=1.00),
        "MSFT": _linear_series(start=start, base=350, slope=0.90, wiggle=1.20),
        "GOOGL": _linear_series(start=start, base=140, slope=0.45, wiggle=0.50),
        "TLT": _linear_series(start=start, base=100, slope=0.07, wiggle=0.10),
        "GLD": _linear_series(start=start, base=100, slope=0.09, wiggle=0.16),
        "USMV": _linear_series(start=start, base=110, slope=0.03, wiggle=0.08),
        "IEF": _linear_series(start=start, base=100, slope=0.06, wiggle=0.06),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _qqq_down_provider() -> FixturePriceProvider:
    """QQQ trends down, VTI trends up -> RISK_OFF (most conservative wins)."""
    start = date(2024, 1, 1)
    series = {
        "VTI": _linear_series(start=start, base=100, slope=0.34, wiggle=0.30),
        "QQQ": _linear_series(start=start, base=210, slope=-0.30, wiggle=0.55),
        "SOXL": _linear_series(start=start, base=80, slope=-0.85, wiggle=1.50),
        "TECL": _linear_series(start=start, base=90, slope=-0.80, wiggle=1.10),
        "FNGU": _linear_series(start=start, base=70, slope=-0.95, wiggle=1.80),
        "NVDL": _linear_series(start=start, base=85, slope=-0.90, wiggle=1.40),
        "SMH": _linear_series(start=start, base=200, slope=-0.40, wiggle=0.60),
        "IGV": _linear_series(start=start, base=160, slope=-0.30, wiggle=0.40),
        "BOTZ": _linear_series(start=start, base=30, slope=-0.05, wiggle=0.10),
        "WCLD": _linear_series(start=start, base=25, slope=-0.04, wiggle=0.08),
        "HACK": _linear_series(start=start, base=60, slope=-0.10, wiggle=0.15),
        "ARKK": _linear_series(start=start, base=50, slope=-0.12, wiggle=0.20),
        "NVDA": _linear_series(start=start, base=600, slope=-1.50, wiggle=2.50),
        "AMD": _linear_series(start=start, base=160, slope=-0.40, wiggle=0.60),
        "AVGO": _linear_series(start=start, base=200, slope=-0.50, wiggle=0.80),
        "MSFT": _linear_series(start=start, base=400, slope=-0.60, wiggle=1.00),
        "GOOGL": _linear_series(start=start, base=170, slope=-0.30, wiggle=0.40),
        "TLT": _linear_series(start=start, base=100, slope=0.07, wiggle=0.10),
        "GLD": _linear_series(start=start, base=100, slope=0.09, wiggle=0.16),
        "USMV": _linear_series(start=start, base=110, slope=0.03, wiggle=0.08),
        "IEF": _linear_series(start=start, base=100, slope=0.06, wiggle=0.06),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _qqq_circuit_breaker_provider() -> FixturePriceProvider:
    """QQQ has >12% drawdown from 63d high, VTI is fine."""
    start = date(2024, 1, 1)
    n = 320
    # QQQ: rises then sharp drop
    qqq_values: list[float] = []
    for idx in range(n):
        if idx < 280:
            qqq_values.append(100 + 0.48 * idx)
        else:
            peak = 100 + 0.48 * 280
            decline_days = idx - 280
            qqq_values.append(peak * (1 - 0.004 * decline_days))  # ~16% drop over 40 days

    series = {
        "VTI": _linear_series(start=start, base=100, slope=0.34, wiggle=0.30, n=n),
        "QQQ": _make_series(start, qqq_values),
        "SOXL": _linear_series(start=start, base=30, slope=0.85, wiggle=1.50, n=n),
        "TECL": _linear_series(start=start, base=40, slope=0.80, wiggle=1.10, n=n),
        "FNGU": _linear_series(start=start, base=25, slope=0.95, wiggle=1.80, n=n),
        "NVDL": _linear_series(start=start, base=35, slope=0.90, wiggle=1.40, n=n),
        "SMH": _linear_series(start=start, base=100, slope=0.50, wiggle=0.50, n=n),
        "IGV": _linear_series(start=start, base=80, slope=0.35, wiggle=0.30, n=n),
        "BOTZ": _linear_series(start=start, base=25, slope=0.20, wiggle=0.15, n=n),
        "WCLD": _linear_series(start=start, base=20, slope=0.15, wiggle=0.12, n=n),
        "HACK": _linear_series(start=start, base=50, slope=0.25, wiggle=0.20, n=n),
        "ARKK": _linear_series(start=start, base=40, slope=0.30, wiggle=0.35, n=n),
        "NVDA": _linear_series(start=start, base=500, slope=2.50, wiggle=3.00, n=n),
        "AMD": _linear_series(start=start, base=120, slope=0.60, wiggle=0.80, n=n),
        "AVGO": _linear_series(start=start, base=150, slope=0.80, wiggle=1.00, n=n),
        "MSFT": _linear_series(start=start, base=350, slope=0.90, wiggle=1.20, n=n),
        "GOOGL": _linear_series(start=start, base=140, slope=0.45, wiggle=0.50, n=n),
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08, n=n),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20, n=n),
        "USMV": _linear_series(start=start, base=100, slope=0.18, wiggle=0.10, n=n),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05, n=n),
        "BIL": _linear_series(start=start, base=100, slope=0.01, n=n),
    }
    return FixturePriceProvider(series)


def _seed_state(repo_root: Path, *, last_regime: str, allocs: dict[str, float],
                last_eval_date: str = "2026-01-31") -> None:
    state_path = repo_root / "state" / "strategies" / raec_401k_v5.BOOK_ID / f"{raec_401k_v5.STRATEGY_ID}.json"
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
# Test: dual anchor regime classification
# ---------------------------------------------------------------------------

def test_regime_risk_on_both_anchors(tmp_path: Path) -> None:
    """VTI + QQQ both up -> RISK_ON."""
    provider = _both_up_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"


def test_regime_risk_off_vti(tmp_path: Path) -> None:
    """VTI down forces RISK_OFF even if QQQ up."""
    provider = _vti_down_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"SOXL": 50.0, "TECL": 50.0})
    result = raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"


def test_regime_risk_off_qqq(tmp_path: Path) -> None:
    """QQQ down forces RISK_OFF even if VTI up."""
    provider = _qqq_down_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"SOXL": 50.0, "TECL": 50.0})
    result = raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"


def test_qqq_circuit_breaker_12pct(tmp_path: Path) -> None:
    """QQQ dd > 12% forces RISK_OFF even if VTI fine."""
    provider = _qqq_circuit_breaker_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"SOXL": 50.0, "TECL": 50.0})
    result = raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"


# ---------------------------------------------------------------------------
# Test: target allocation structure
# ---------------------------------------------------------------------------

def test_risk_on_top_2(tmp_path: Path) -> None:
    """V5 selects top 2 risk symbols in RISK_ON."""
    provider = _both_up_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"
    assert round(sum(result.targets.values()), 1) == 100.0
    risk_symbols = [sym for sym in result.targets if sym not in ("BIL",)]
    assert len(risk_symbols) <= 2
    assert set(risk_symbols).issubset(set(raec_401k_v5.RISK_UNIVERSE))


def test_risk_on_zero_cash(tmp_path: Path) -> None:
    """BIL can be 0% or absent in RISK_ON (cash floor is 0%)."""
    provider = _both_up_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"
    cash_pct = result.targets.get("BIL", 0.0)
    assert cash_pct < 10.0


def test_risk_on_max_weight_70(tmp_path: Path) -> None:
    """Single position can reach up to 70% in V5."""
    provider = _both_up_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_ON"
    for sym, pct in result.targets.items():
        assert pct <= 71.0, f"{sym} weight {pct}% exceeds 70% cap"


def test_risk_off_defensive(tmp_path: Path) -> None:
    """RISK_OFF: ~80% defensive, ~20% cash."""
    provider = _vti_down_provider()
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"SOXL": 50.0, "TECL": 50.0})
    result = raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.regime == "RISK_OFF"
    assert round(sum(result.targets.values()), 1) == 100.0
    cash_pct = result.targets.get("BIL", 0.0)
    assert cash_pct >= 19.5
    assert cash_pct <= 25.0
    risk_in_targets = set(result.targets.keys()) & set(raec_401k_v5.RISK_UNIVERSE)
    assert len(risk_in_targets) == 0


def test_transition_structure(tmp_path: Path) -> None:
    """Risk + defensive + 5% cash floor."""
    start = date(2024, 1, 1)
    # VTI: above SMA200 but with mild drawdown -> TRANSITION
    vti_values: list[float] = []
    for idx in range(320):
        if idx < 290:
            vti_values.append(100 + 0.30 * idx)
        else:
            peak = 100 + 0.30 * 290
            decline_days = idx - 290
            vti_values.append(peak * (1 - 0.002 * decline_days))

    # QQQ also mild drawdown for TRANSITION
    qqq_values: list[float] = []
    for idx in range(320):
        if idx < 290:
            qqq_values.append(100 + 0.40 * idx)
        else:
            peak = 100 + 0.40 * 290
            decline_days = idx - 290
            qqq_values.append(peak * (1 - 0.002 * decline_days))

    series = {
        "VTI": _make_series(start, vti_values),
        "QQQ": _make_series(start, qqq_values),
        "SOXL": _linear_series(start=start, base=30, slope=0.85, wiggle=1.50),
        "TECL": _linear_series(start=start, base=40, slope=0.80, wiggle=1.10),
        "FNGU": _linear_series(start=start, base=25, slope=0.95, wiggle=1.80),
        "NVDL": _linear_series(start=start, base=35, slope=0.90, wiggle=1.40),
        "SMH": _linear_series(start=start, base=100, slope=0.50, wiggle=0.50),
        "IGV": _linear_series(start=start, base=80, slope=0.35, wiggle=0.30),
        "BOTZ": _linear_series(start=start, base=25, slope=0.20, wiggle=0.15),
        "WCLD": _linear_series(start=start, base=20, slope=0.15, wiggle=0.12),
        "HACK": _linear_series(start=start, base=50, slope=0.25, wiggle=0.20),
        "ARKK": _linear_series(start=start, base=40, slope=0.30, wiggle=0.35),
        "NVDA": _linear_series(start=start, base=500, slope=2.50, wiggle=3.00),
        "AMD": _linear_series(start=start, base=120, slope=0.60, wiggle=0.80),
        "AVGO": _linear_series(start=start, base=150, slope=0.80, wiggle=1.00),
        "MSFT": _linear_series(start=start, base=350, slope=0.90, wiggle=1.20),
        "GOOGL": _linear_series(start=start, base=140, slope=0.45, wiggle=0.50),
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20),
        "USMV": _linear_series(start=start, base=100, slope=0.18, wiggle=0.10),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    provider = FixturePriceProvider(series)
    _seed_state(tmp_path, last_regime="RISK_ON", allocs={"SOXL": 50.0, "TECL": 50.0})
    result = raec_401k_v5.run_strategy(
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
# Test: daily rebalance trigger
# ---------------------------------------------------------------------------

def test_daily_rebalance_trigger(tmp_path: Path) -> None:
    provider = _both_up_provider()
    asof_date = "2026-02-06"
    asof = raec_401k_v5._parse_date(asof_date)
    cash_symbol = raec_401k_v5._get_cash_symbol(provider)
    vti_series = raec_401k_v5._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
    qqq_series = raec_401k_v5._sorted_series(provider.get_daily_close_series("QQQ"), asof=asof)
    signal = raec_401k_v5._compute_anchor_signal(vti_series, qqq_series)
    feature_map = raec_401k_v5._load_symbol_features(provider=provider, asof=asof, cash_symbol=cash_symbol)
    targets = raec_401k_v5._targets_for_regime(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)

    _seed_state(tmp_path, last_regime=signal.regime, allocs=targets,
                last_eval_date=asof_date)
    result_same_day = raec_401k_v5.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    _seed_state(tmp_path, last_regime=signal.regime, allocs=targets,
                last_eval_date="2026-02-05")
    result_new_day = raec_401k_v5.run_strategy(
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
    provider = _both_up_provider()
    asof_date = "2026-02-06"
    asof = raec_401k_v5._parse_date(asof_date)
    cash_symbol = raec_401k_v5._get_cash_symbol(provider)
    vti_series = raec_401k_v5._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
    qqq_series = raec_401k_v5._sorted_series(provider.get_daily_close_series("QQQ"), asof=asof)
    signal = raec_401k_v5._compute_anchor_signal(vti_series, qqq_series)
    feature_map = raec_401k_v5._load_symbol_features(provider=provider, asof=asof, cash_symbol=cash_symbol)
    targets = raec_401k_v5._targets_for_regime(signal=signal, feature_map=feature_map, cash_symbol=cash_symbol)

    close_allocs = {sym: pct for sym, pct in targets.items()}
    first_sym = next(iter(close_allocs))
    close_allocs[first_sym] += 1.4
    other_syms = [s for s in close_allocs if s != first_sym]
    if other_syms:
        close_allocs[other_syms[0]] -= 1.4

    _seed_state(tmp_path, last_regime=signal.regime, allocs=close_allocs,
                last_eval_date="2026-02-06")
    result_no = raec_401k_v5.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    assert result_no.should_rebalance is False

    drift_allocs = {sym: pct for sym, pct in targets.items()}
    drift_allocs[first_sym] += 1.6
    if other_syms:
        drift_allocs[other_syms[0]] -= 1.6

    _seed_state(tmp_path, last_regime=signal.regime, allocs=drift_allocs,
                last_eval_date="2026-02-06")
    result_yes = raec_401k_v5.run_strategy(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        allow_state_write=False,
    )
    assert result_yes.should_rebalance is True


# ---------------------------------------------------------------------------
# Test: turnover cap 45%
# ---------------------------------------------------------------------------

def test_turnover_cap_45() -> None:
    intents = raec_401k_v5._build_intents(
        asof_date="2026-02-06",
        targets={"SOXL": 55.0, "TECL": 45.0},
        current={"BIL": 100.0},
        max_weekly_turnover=45.0,
    )
    buys = [intent for intent in intents if intent["side"] == "BUY"]
    total_buy_delta = sum(float(intent["delta_pct"]) for intent in buys)
    assert total_buy_delta == pytest.approx(45.0, abs=0.5)


# ---------------------------------------------------------------------------
# Test: 3-month momentum filter
# ---------------------------------------------------------------------------

def test_momentum_3m_filter() -> None:
    base_returns = tuple([0.01, -0.005, 0.008, -0.004, 0.006, -0.003] * 11)
    good = raec_401k_v5.SymbolFeature(
        symbol="SOXL", close=100.0, mom_3m=0.15, mom_6m=0.20, mom_12m=0.25,
        vol_20d=0.30, vol_252d=0.30, drawdown_63d=-0.05, score=1.5,
        returns_window=base_returns,
    )
    bad = raec_401k_v5.SymbolFeature(
        symbol="TECL", close=100.0, mom_3m=-0.10, mom_6m=0.05, mom_12m=0.10,
        vol_20d=0.35, vol_252d=0.35, drawdown_63d=-0.15, score=0.5,
        returns_window=base_returns,
    )
    feature_map = {"SOXL": good, "TECL": bad}
    ranked = raec_401k_v5._rank_symbols(
        ["SOXL", "TECL"], feature_map, require_positive_momentum=True
    )
    assert "SOXL" in ranked
    assert "TECL" not in ranked


# ---------------------------------------------------------------------------
# Test: intent ID deterministic and different from V3/V4
# ---------------------------------------------------------------------------

def test_intent_id_deterministic() -> None:
    id1 = raec_401k_v5._intent_id(
        asof_date="2026-02-06", symbol="SOXL", side="BUY", target_pct=55.0
    )
    id2 = raec_401k_v5._intent_id(
        asof_date="2026-02-06", symbol="SOXL", side="BUY", target_pct=55.0
    )
    assert id1 == id2

    id_v3 = raec_401k_v3._intent_id(
        asof_date="2026-02-06", symbol="SOXL", side="BUY", target_pct=55.0
    )
    id_v4 = raec_401k_v4._intent_id(
        asof_date="2026-02-06", symbol="SOXL", side="BUY", target_pct=55.0
    )
    assert id1 != id_v3
    assert id1 != id_v4


# ---------------------------------------------------------------------------
# Test: dry_run no adapter
# ---------------------------------------------------------------------------

def test_dry_run_no_slack(tmp_path: Path) -> None:
    provider = _both_up_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})

    class MockAdapter:
        called = False

        def send_summary_ticket(self, *args, **kwargs):
            MockAdapter.called = True
            raise AssertionError("Adapter should not be called in dry_run")

    result = raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        adapter_override=MockAdapter(),
    )
    assert not MockAdapter.called
    assert result.should_rebalance is True


# ---------------------------------------------------------------------------
# Test: state persistence (includes dual anchor info)
# ---------------------------------------------------------------------------

def test_state_persists(tmp_path: Path) -> None:
    provider = _both_up_provider()
    _seed_state(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})

    raec_401k_v5.run_strategy(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=False,
        allow_state_write=True,
        adapter_override=_NoOpAdapter(),
    )

    state_path = tmp_path / "state" / "strategies" / raec_401k_v5.BOOK_ID / f"{raec_401k_v5.STRATEGY_ID}.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["last_eval_date"] == "2026-02-06"
    assert state["last_regime"] in ("RISK_ON", "TRANSITION", "RISK_OFF")
    assert isinstance(state["last_targets"], dict)
    assert isinstance(state["last_known_allocations"], dict)
    # V5 saves QQQ anchor data
    assert "qqq_close" in state
    assert "qqq_sma50" in state
    assert "qqq_sma200" in state
    assert "qqq_drawdown_63d" in state
