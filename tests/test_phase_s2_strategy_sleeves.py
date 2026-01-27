from __future__ import annotations

from execution_v2.config_types import EntryIntent, PositionState, StopMode
from execution_v2.portfolio_s2_enforcement import (
    REASON_MAX_DAILY_LOSS,
    REASON_MAX_GROSS_EXPOSURE,
    REASON_MAX_POSITIONS,
    REASON_MISSING_PNL,
    REASON_MISSING_SLEEVE,
    REASON_SYMBOL_OVERLAP,
    enforce_sleeves,
)
from execution_v2.strategy_sleeves import SleeveConfig, StrategySleeve


def _entry(
    strategy_id: str,
    symbol: str,
    qty: int,
    ref_price: float,
) -> EntryIntent:
    return EntryIntent(
        strategy_id=strategy_id,
        symbol=symbol,
        pivot_level=0.0,
        boh_confirmed_at=1.0,
        scheduled_entry_at=2.0,
        size_shares=qty,
        stop_loss=0.0,
        take_profit=0.0,
        ref_price=ref_price,
        dist_pct=0.0,
    )


def _position(
    strategy_id: str,
    symbol: str,
    qty: int,
    avg_price: float,
) -> PositionState:
    return PositionState(
        strategy_id=strategy_id,
        symbol=symbol,
        size_shares=qty,
        avg_price=avg_price,
        pivot_level=0.0,
        r1_level=0.0,
        r2_level=0.0,
        stop_mode=StopMode.OPEN,
        last_update_ts=1.0,
        stop_price=0.0,
        high_water=0.0,
        last_boh_level=None,
        invalidation_count=0,
        trimmed_r1=False,
        trimmed_r2=False,
    )


def test_sleeve_blocks_max_positions() -> None:
    intents = [_entry("alpha", "AAA", 10, 10.0)]
    positions = [_position("alpha", "BBB", 5, 10.0)]
    config = SleeveConfig(
        sleeves={"alpha": StrategySleeve(max_concurrent_positions=1)},
        allow_unsleeved=False,
        allow_symbol_overlap=False,
        daily_pnl_by_strategy={},
    )

    result = enforce_sleeves(intents=intents, positions=positions, config=config)

    assert result.approved == []
    assert len(result.blocked) == 1
    assert REASON_MAX_POSITIONS in result.blocked[0].reason_codes


def test_sleeve_blocks_max_gross_exposure() -> None:
    intents = [_entry("alpha", "AAA", 10, 10.0)]
    positions = [_position("alpha", "BBB", 10, 100.0)]
    config = SleeveConfig(
        sleeves={"alpha": StrategySleeve(max_gross_exposure_usd=1050.0)},
        allow_unsleeved=False,
        allow_symbol_overlap=False,
        daily_pnl_by_strategy={},
    )

    result = enforce_sleeves(intents=intents, positions=positions, config=config)

    assert result.approved == []
    assert len(result.blocked) == 1
    assert REASON_MAX_GROSS_EXPOSURE in result.blocked[0].reason_codes


def test_sleeve_blocks_max_daily_loss() -> None:
    intents = [_entry("alpha", "AAA", 10, 10.0)]
    config = SleeveConfig(
        sleeves={"alpha": StrategySleeve(max_daily_loss_usd=100.0)},
        allow_unsleeved=False,
        allow_symbol_overlap=False,
        daily_pnl_by_strategy={"alpha": -150.0},
    )

    result = enforce_sleeves(intents=intents, positions=[], config=config)

    assert result.approved == []
    assert len(result.blocked) == 1
    assert REASON_MAX_DAILY_LOSS in result.blocked[0].reason_codes


def test_sleeve_blocks_missing_daily_pnl() -> None:
    intents = [_entry("alpha", "AAA", 10, 10.0)]
    config = SleeveConfig(
        sleeves={"alpha": StrategySleeve(max_daily_loss_usd=100.0)},
        allow_unsleeved=False,
        allow_symbol_overlap=False,
        daily_pnl_by_strategy={},
    )

    result = enforce_sleeves(intents=intents, positions=[], config=config)

    assert result.approved == []
    assert len(result.blocked) == 1
    assert REASON_MISSING_PNL in result.blocked[0].reason_codes


def test_symbol_overlap_blocked() -> None:
    intents = [_entry("beta", "AAA", 10, 10.0)]
    positions = [_position("alpha", "AAA", 5, 10.0)]
    config = SleeveConfig(
        sleeves={"alpha": StrategySleeve(), "beta": StrategySleeve()},
        allow_unsleeved=False,
        allow_symbol_overlap=False,
        daily_pnl_by_strategy={},
    )

    result = enforce_sleeves(intents=intents, positions=positions, config=config)

    assert result.approved == []
    assert len(result.blocked) == 1
    assert REASON_SYMBOL_OVERLAP in result.blocked[0].reason_codes


def test_missing_sleeve_blocks_all_entries() -> None:
    intents = [_entry("beta", "AAA", 10, 10.0)]
    positions = [_position("alpha", "BBB", 5, 10.0)]
    config = SleeveConfig(
        sleeves={},
        allow_unsleeved=False,
        allow_symbol_overlap=True,
        daily_pnl_by_strategy={},
    )

    result = enforce_sleeves(intents=intents, positions=positions, config=config)

    assert result.blocked_all is True
    assert result.approved == []
    assert len(result.blocked) == 1
    assert REASON_MISSING_SLEEVE in result.blocked[0].reason_codes


def test_deterministic_ordering() -> None:
    intents = [
        _entry("alpha", "ZZZ", 10, 10.0),
        _entry("alpha", "AAA", 10, 10.0),
    ]
    config = SleeveConfig(
        sleeves={"alpha": StrategySleeve(max_daily_loss_usd=1.0)},
        allow_unsleeved=False,
        allow_symbol_overlap=True,
        daily_pnl_by_strategy={"alpha": -100.0},
    )

    result = enforce_sleeves(intents=intents, positions=[], config=config)

    assert [blocked.intent.symbol for blocked in result.blocked] == ["AAA", "ZZZ"]
