"""Tests for v6 dataclasses: StrategyManifest, StrategyOutput, SignalState."""

from __future__ import annotations

from datetime import date

import pytest

from strategies.raec_v6.manifest import StrategyManifest
from strategies.raec_v6.signal_state import SignalState
from strategies.raec_v6.strategy_output import StrategyOutput


def _man(sid: str = "X") -> StrategyManifest:
    return StrategyManifest(strategy_id=sid, asset_classes=("equity_us_broad",))


def test_manifest_defaults() -> None:
    m = _man()
    assert m.history_quality == "robust"
    assert m.max_share_cap == 1.0
    assert m.backtest_oos_sharpe == 0.0


def test_output_validates_conviction_range() -> None:
    with pytest.raises(ValueError, match="conviction"):
        StrategyOutput(
            weights={"SPY": 0.5},
            conviction=1.5,
            regime_gate=1.0,
            realized_vol_60d=0.16,
            manifest=_man(),
        )


def test_output_validates_regime_gate_discrete() -> None:
    with pytest.raises(ValueError, match="regime_gate"):
        StrategyOutput(
            weights={"SPY": 0.5},
            conviction=0.5,
            regime_gate=0.75,
            realized_vol_60d=0.16,
            manifest=_man(),
        )


def test_output_rejects_negative_weight() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        StrategyOutput(
            weights={"SPY": -0.1},
            conviction=0.5,
            regime_gate=1.0,
            realized_vol_60d=0.16,
            manifest=_man(),
        )


def test_output_rejects_weights_summing_above_one() -> None:
    with pytest.raises(ValueError, match="sum to <= 1"):
        StrategyOutput(
            weights={"SPY": 0.6, "QQQ": 0.5},
            conviction=0.5,
            regime_gate=1.0,
            realized_vol_60d=0.16,
            manifest=_man(),
        )


def test_output_allows_weights_summing_below_one() -> None:
    # Residual is the strategy's own cash bucket; OK to under-deploy.
    o = StrategyOutput(
        weights={"SPY": 0.3},
        conviction=0.5,
        regime_gate=1.0,
        realized_vol_60d=0.16,
        manifest=_man(),
    )
    assert sum(o.weights.values()) == 0.3


def test_signal_state_default_collections_empty() -> None:
    s = SignalState(asof_date=date(2026, 6, 8), regime_label="NEUTRAL", regime_confidence=0.5)
    assert s.cross_asset_trend == {}
    assert s.vol_percentile_252d == {}
    assert s.vix_implied == 0.0
