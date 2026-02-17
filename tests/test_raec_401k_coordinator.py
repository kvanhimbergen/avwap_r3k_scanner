from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from data.prices import FixturePriceProvider
from strategies import raec_401k_coordinator, raec_401k_v3, raec_401k_v4, raec_401k_v5


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


def _all_risk_on_provider() -> FixturePriceProvider:
    """Provider with uptrending prices for all universes -> RISK_ON."""
    start = date(2024, 1, 1)
    series = {
        # Anchors
        "VTI": _linear_series(start=start, base=100, slope=0.34, wiggle=0.30),
        "QQQ": _linear_series(start=start, base=100, slope=0.48, wiggle=0.45),
        # V3 risk universe
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
        "SPY": _linear_series(start=start, base=100, slope=0.30, wiggle=0.25),
        # V4 risk universe (additions)
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
        # V5 additions (individual stocks + extra ETFs)
        "NVDL": _linear_series(start=start, base=35, slope=0.90, wiggle=1.40),
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
        # Defensive (shared)
        "TLT": _linear_series(start=start, base=100, slope=0.06, wiggle=0.08),
        "GLD": _linear_series(start=start, base=100, slope=0.13, wiggle=0.20),
        "USMV": _linear_series(start=start, base=100, slope=0.18, wiggle=0.10),
        "IEF": _linear_series(start=start, base=100, slope=0.08, wiggle=0.05),
        "UUP": _linear_series(start=start, base=28, slope=0.03, wiggle=0.02),
        "SHY": _linear_series(start=start, base=84, slope=0.02, wiggle=0.01),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _all_risk_off_provider() -> FixturePriceProvider:
    """Provider with downtrending prices -> RISK_OFF for all."""
    start = date(2024, 1, 1)
    series = {
        "VTI": _linear_series(start=start, base=210, slope=-0.30, wiggle=0.55),
        "QQQ": _linear_series(start=start, base=210, slope=-0.35, wiggle=0.65),
        "TQQQ": _linear_series(start=start, base=100, slope=-0.90, wiggle=1.50),
        "SOXL": _linear_series(start=start, base=80, slope=-0.85, wiggle=1.80),
        "UPRO": _linear_series(start=start, base=120, slope=-0.70, wiggle=1.10),
        "TECL": _linear_series(start=start, base=90, slope=-0.80, wiggle=1.30),
        "FNGU": _linear_series(start=start, base=70, slope=-0.95, wiggle=2.00),
        "XLK": _linear_series(start=start, base=200, slope=-0.35, wiggle=0.50),
        "SMH": _linear_series(start=start, base=200, slope=-0.40, wiggle=0.60),
        "XLY": _linear_series(start=start, base=180, slope=-0.25, wiggle=0.35),
        "XLC": _linear_series(start=start, base=170, slope=-0.22, wiggle=0.30),
        "XLI": _linear_series(start=start, base=160, slope=-0.18, wiggle=0.25),
        "SPY": _linear_series(start=start, base=210, slope=-0.26, wiggle=0.45),
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
        "NVDL": _linear_series(start=start, base=85, slope=-0.90, wiggle=1.40),
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
        "UUP": _linear_series(start=start, base=28, slope=0.04, wiggle=0.02),
        "SHY": _linear_series(start=start, base=84, slope=0.02, wiggle=0.01),
        "BIL": _linear_series(start=start, base=100, slope=0.01),
    }
    return FixturePriceProvider(series)


def _seed_all_states(repo_root: Path, *, last_regime: str, allocs: dict[str, float],
                     last_eval_date: str = "2026-01-31") -> None:
    """Seed state for all three sub-strategies."""
    for module in (raec_401k_v3, raec_401k_v4, raec_401k_v5):
        state_path = repo_root / "state" / "strategies" / module.BOOK_ID / f"{module.STRATEGY_ID}.json"
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


class _TrackingAdapter:
    def __init__(self):
        self.calls = []

    def send_summary_ticket(self, intents, *, message="", ny_date="", repo_root=None, post_enabled=True):
        self.calls.append({"intents": intents, "message": message, "ny_date": ny_date})
        return _SendResult()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_coordinator_runs_all_three(tmp_path: Path) -> None:
    provider = _all_risk_on_provider()
    _seed_all_states(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_coordinator.run_coordinator(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert "v3" in result.sub_results
    assert "v4" in result.sub_results
    assert "v5" in result.sub_results


def test_coordinator_capital_split(tmp_path: Path) -> None:
    provider = _all_risk_on_provider()
    _seed_all_states(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    result = raec_401k_coordinator.run_coordinator(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    assert result.capital_split == {"v3": 0.40, "v4": 0.30, "v5": 0.30}


def test_coordinator_dry_run_no_adapter(tmp_path: Path) -> None:
    provider = _all_risk_on_provider()
    _seed_all_states(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})

    adapter = _TrackingAdapter()
    result = raec_401k_coordinator.run_coordinator(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
        adapter_override=adapter,
    )
    assert len(adapter.calls) == 0
    assert len(result.posted) == 0


def test_coordinator_posts_separate_tickets(tmp_path: Path) -> None:
    provider = _all_risk_on_provider()
    _seed_all_states(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})

    adapter = _TrackingAdapter()
    result = raec_401k_coordinator.run_coordinator(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=False,
        adapter_override=adapter,
    )
    # All three should have posted
    assert len(adapter.calls) == 3
    assert len(result.posted) == 3


def test_coordinator_state_persists(tmp_path: Path) -> None:
    provider = _all_risk_on_provider()
    _seed_all_states(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    raec_401k_coordinator.run_coordinator(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    state_path = tmp_path / "state" / "strategies" / raec_401k_coordinator.BOOK_ID / f"{raec_401k_coordinator.STRATEGY_ID}.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["last_eval_date"] == "2026-02-06"
    assert "sub_regimes" in state
    assert set(state["sub_regimes"].keys()) == {"v3", "v4", "v5"}


def test_sub_strategies_update_own_state(tmp_path: Path) -> None:
    provider = _all_risk_on_provider()
    _seed_all_states(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    raec_401k_coordinator.run_coordinator(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    for module in (raec_401k_v3, raec_401k_v4, raec_401k_v5):
        state_path = tmp_path / "state" / "strategies" / module.BOOK_ID / f"{module.STRATEGY_ID}.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text())
        assert state["last_eval_date"] == "2026-02-06"


def test_coordinator_summary_output(tmp_path: Path, capsys) -> None:
    provider = _all_risk_on_provider()
    _seed_all_states(tmp_path, last_regime="RISK_OFF", allocs={"BIL": 100.0})
    raec_401k_coordinator.run_coordinator(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    captured = capsys.readouterr()
    assert "COORD Summary:" in captured.out
    assert "V3=" in captured.out
    assert "V4=" in captured.out
    assert "V5=" in captured.out


def test_coordinator_partial_rebalance(tmp_path: Path) -> None:
    """Only sub-strategies that should rebalance get tickets posted."""
    provider = _all_risk_on_provider()
    # Seed V3 state so it won't rebalance (same day, same regime, allocs at target)
    asof_date = "2026-02-06"
    asof = raec_401k_v3._parse_date(asof_date)
    cash_symbol = "BIL"
    vti_series = raec_401k_v3._sorted_series(provider.get_daily_close_series("VTI"), asof=asof)
    signal = raec_401k_v3._compute_anchor_signal(vti_series)
    fm = raec_401k_v3._load_symbol_features(provider=provider, asof=asof, cash_symbol=cash_symbol)
    v3_targets = raec_401k_v3._targets_for_regime(signal=signal, feature_map=fm, cash_symbol=cash_symbol)

    # V3 state: same day, same regime, allocs at target -> no rebalance
    v3_state_path = tmp_path / "state" / "strategies" / raec_401k_v3.BOOK_ID / f"{raec_401k_v3.STRATEGY_ID}.json"
    v3_state_path.parent.mkdir(parents=True, exist_ok=True)
    v3_state_path.write_text(json.dumps({
        "last_eval_date": asof_date,
        "last_regime": signal.regime,
        "last_known_allocations": v3_targets,
    }))

    # V4/V5: seed with stale state so they DO rebalance
    for module in (raec_401k_v4, raec_401k_v5):
        sp = tmp_path / "state" / "strategies" / module.BOOK_ID / f"{module.STRATEGY_ID}.json"
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps({
            "last_eval_date": "2026-01-31",
            "last_regime": "RISK_OFF",
            "last_known_allocations": {"BIL": 100.0},
        }))

    adapter = _TrackingAdapter()
    result = raec_401k_coordinator.run_coordinator(
        asof_date=asof_date,
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=False,
        adapter_override=adapter,
    )
    # V3 should NOT rebalance, V4 and V5 should
    assert "v3" not in result.rebalanced
    assert "v4" in result.rebalanced
    assert "v5" in result.rebalanced
    assert len(adapter.calls) == 2


def test_coordinator_cli_args() -> None:
    args = raec_401k_coordinator.parse_args(["--asof", "2026-02-17", "--dry-run"])
    assert args.asof == "2026-02-17"
    assert args.dry_run is True


def test_coordinator_all_risk_off(tmp_path: Path) -> None:
    provider = _all_risk_off_provider()
    _seed_all_states(tmp_path, last_regime="RISK_ON", allocs={"TQQQ": 50.0, "SOXL": 50.0})
    result = raec_401k_coordinator.run_coordinator(
        asof_date="2026-02-06",
        repo_root=tmp_path,
        price_provider=provider,
        dry_run=True,
    )
    for key in ("v3", "v4", "v5"):
        assert result.sub_results[key].regime == "RISK_OFF"
