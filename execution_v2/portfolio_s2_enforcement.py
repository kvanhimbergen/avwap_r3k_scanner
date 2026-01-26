"""
Execution V2 – Strategy Sleeve Enforcement (Phase S2).
"""

from __future__ import annotations

from dataclasses import dataclass

from execution_v2.config_types import EntryIntent, PositionState
from execution_v2.portfolio_intents import RejectedIntent, TradeIntent
from execution_v2.strategy_sleeves import SleeveConfig, StrategySleeve

REASON_MISSING_SLEEVE = "s2_missing_sleeve"
REASON_MAX_POSITIONS = "s2_max_positions"
REASON_MAX_GROSS_EXPOSURE = "s2_max_gross_exposure"
REASON_SYMBOL_OVERLAP = "s2_symbol_overlap"
REASON_MAX_DAILY_LOSS = "s2_max_daily_loss"

MAX_BLOCKED_SAMPLE = 25


@dataclass(frozen=True)
class BlockedIntent:
    intent: EntryIntent
    rejection_reason: str
    reason_codes: list[str]


@dataclass(frozen=True)
class StrategySummary:
    strategy_id: str
    open_positions: int
    approved_new_positions: int
    blocked_new_positions: int
    gross_exposure_current: float
    gross_exposure_projected: float
    max_concurrent_positions: int | None
    max_gross_exposure_usd: float | None
    max_daily_loss_usd: float | None


@dataclass(frozen=True)
class EnforcementResult:
    approved: list[EntryIntent]
    blocked: list[BlockedIntent]
    strategy_summaries: dict[str, StrategySummary]
    portfolio_summary: dict[str, float | int]
    reason_counts: dict[str, int]
    blocked_sample: list[dict[str, object]]
    blocked_all: bool
    errors: list[str]


def enforce_sleeves(
    *,
    intents: list[EntryIntent],
    positions: list[PositionState],
    config: SleeveConfig,
) -> EnforcementResult:
    errors: list[str] = []
    open_symbols_by_strategy: dict[str, set[str]] = {}
    open_symbols_to_strategy: dict[str, str] = {}
    gross_by_strategy: dict[str, float] = {}

    for position in positions:
        strategy_id = str(position.strategy_id)
        symbol = str(position.symbol)
        open_symbols_by_strategy.setdefault(strategy_id, set()).add(symbol)
        if symbol not in open_symbols_to_strategy:
            open_symbols_to_strategy[symbol] = strategy_id
        gross_by_strategy[strategy_id] = gross_by_strategy.get(strategy_id, 0.0) + _position_notional(
            position
        )

    missing_sleeves = _find_missing_sleeves(
        intents=intents,
        positions=positions,
        config=config,
    )
    blocked: list[BlockedIntent] = []
    approved: list[EntryIntent] = []
    blocked_all = False

    if missing_sleeves and not config.allow_unsleeved:
        blocked_all = True
        for intent in _sorted_intents(intents):
            blocked.append(
                BlockedIntent(
                    intent=intent,
                    rejection_reason=REASON_MISSING_SLEEVE,
                    reason_codes=[REASON_MISSING_SLEEVE],
                )
            )
    else:
        approved_by_strategy: dict[str, int] = {}
        added_gross_by_strategy: dict[str, float] = {}
        for intent in _sorted_intents(intents):
            strategy_id = str(intent.strategy_id)
            sleeve = config.sleeves.get(strategy_id)
            if sleeve is None and not config.allow_unsleeved:
                blocked.append(
                    BlockedIntent(
                        intent=intent,
                        rejection_reason=REASON_MISSING_SLEEVE,
                        reason_codes=[REASON_MISSING_SLEEVE],
                    )
                )
                continue
            reason_codes: list[str] = []
            if not config.allow_symbol_overlap:
                overlap_strategy = open_symbols_to_strategy.get(intent.symbol)
                if overlap_strategy and overlap_strategy != strategy_id:
                    reason_codes.append(REASON_SYMBOL_OVERLAP)
            if sleeve:
                reason_codes.extend(
                    _evaluate_sleeve(
                        sleeve=sleeve,
                        strategy_id=strategy_id,
                        intent=intent,
                        open_symbols_by_strategy=open_symbols_by_strategy,
                        approved_by_strategy=approved_by_strategy,
                        gross_by_strategy=gross_by_strategy,
                        added_gross_by_strategy=added_gross_by_strategy,
                        daily_pnl_by_strategy=config.daily_pnl_by_strategy,
                    )
                )
            if reason_codes:
                blocked.append(
                    BlockedIntent(
                        intent=intent,
                        rejection_reason=reason_codes[0],
                        reason_codes=sorted(set(reason_codes)),
                    )
                )
                continue
            approved.append(intent)
            approved_by_strategy[strategy_id] = approved_by_strategy.get(strategy_id, 0) + 1
            notional = _intent_notional(intent)
            added_gross_by_strategy[strategy_id] = (
                added_gross_by_strategy.get(strategy_id, 0.0) + notional
            )

    strategy_summaries = _build_strategy_summaries(
        config=config,
        intents=intents,
        positions=positions,
        approved=approved,
        blocked=blocked,
    )
    portfolio_summary = _build_portfolio_summary(
        positions=positions, approved=approved
    )
    reason_counts: dict[str, int] = {}
    for entry in blocked:
        for code in entry.reason_codes:
            reason_counts[code] = reason_counts.get(code, 0) + 1
    reason_counts = dict(sorted(reason_counts.items()))

    blocked_sample = [
        {
            "strategy_id": intent.intent.strategy_id,
            "symbol": intent.intent.symbol,
            "reason_codes": intent.reason_codes,
        }
        for intent in blocked[:MAX_BLOCKED_SAMPLE]
    ]

    return EnforcementResult(
        approved=approved,
        blocked=blocked,
        strategy_summaries=strategy_summaries,
        portfolio_summary=portfolio_summary,
        reason_counts=reason_counts,
        blocked_sample=blocked_sample,
        blocked_all=blocked_all,
        errors=errors,
    )


def append_rejections(
    *,
    rejected: list[RejectedIntent],
    blocked: list[BlockedIntent],
) -> None:
    for entry in blocked:
        trade_intent = _trade_intent_from_entry(entry.intent)
        rejected.append(
            RejectedIntent(
                intent=trade_intent,
                rejection_reason=entry.rejection_reason,
                reason_codes=entry.reason_codes,
            )
        )


def _find_missing_sleeves(
    *,
    intents: list[EntryIntent],
    positions: list[PositionState],
    config: SleeveConfig,
) -> set[str]:
    strategy_ids = {intent.strategy_id for intent in intents}
    strategy_ids.update(position.strategy_id for position in positions)
    missing = {strategy_id for strategy_id in strategy_ids if strategy_id not in config.sleeves}
    return missing


def _evaluate_sleeve(
    *,
    sleeve: StrategySleeve,
    strategy_id: str,
    intent: EntryIntent,
    open_symbols_by_strategy: dict[str, set[str]],
    approved_by_strategy: dict[str, int],
    gross_by_strategy: dict[str, float],
    added_gross_by_strategy: dict[str, float],
    daily_pnl_by_strategy: dict[str, float],
) -> list[str]:
    reason_codes: list[str] = []
    if sleeve.max_daily_loss_usd is not None:
        pnl = daily_pnl_by_strategy.get(strategy_id)
        if pnl is None or pnl <= -float(sleeve.max_daily_loss_usd):
            reason_codes.append(REASON_MAX_DAILY_LOSS)
    if sleeve.max_concurrent_positions is not None:
        open_count = len(open_symbols_by_strategy.get(strategy_id, set()))
        approved_count = approved_by_strategy.get(strategy_id, 0)
        if open_count + approved_count >= int(sleeve.max_concurrent_positions):
            reason_codes.append(REASON_MAX_POSITIONS)
    if sleeve.max_gross_exposure_usd is not None:
        notional = _intent_notional(intent)
        current = gross_by_strategy.get(strategy_id, 0.0)
        added = added_gross_by_strategy.get(strategy_id, 0.0)
        projected = current + added + notional
        if projected > float(sleeve.max_gross_exposure_usd):
            reason_codes.append(REASON_MAX_GROSS_EXPOSURE)
    return reason_codes


def _intent_notional(intent: EntryIntent) -> float:
    qty = float(intent.size_shares)
    ref_price = float(intent.ref_price)
    return abs(qty * ref_price)


def _position_notional(position: PositionState) -> float:
    qty = float(position.size_shares)
    price = float(position.avg_price)
    return abs(qty * price)


def _sorted_intents(intents: list[EntryIntent]) -> list[EntryIntent]:
    return sorted(intents, key=lambda item: (item.symbol, item.strategy_id, int(item.size_shares)))


def _trade_intent_from_entry(intent: EntryIntent) -> TradeIntent:
    from execution_v2.portfolio_intents import trade_intent_from_entry_intent

    return trade_intent_from_entry_intent(intent)


def _build_strategy_summaries(
    *,
    config: SleeveConfig,
    intents: list[EntryIntent],
    positions: list[PositionState],
    approved: list[EntryIntent],
    blocked: list[BlockedIntent],
) -> dict[str, StrategySummary]:
    open_symbols_by_strategy: dict[str, set[str]] = {}
    gross_by_strategy: dict[str, float] = {}
    for position in positions:
        open_symbols_by_strategy.setdefault(position.strategy_id, set()).add(position.symbol)
        gross_by_strategy[position.strategy_id] = gross_by_strategy.get(position.strategy_id, 0.0) + _position_notional(
            position
        )

    approved_count: dict[str, int] = {}
    approved_gross: dict[str, float] = {}
    for intent in approved:
        approved_count[intent.strategy_id] = approved_count.get(intent.strategy_id, 0) + 1
        approved_gross[intent.strategy_id] = approved_gross.get(intent.strategy_id, 0.0) + _intent_notional(
            intent
        )

    blocked_count: dict[str, int] = {}
    for entry in blocked:
        blocked_count[entry.intent.strategy_id] = blocked_count.get(entry.intent.strategy_id, 0) + 1

    summaries: dict[str, StrategySummary] = {}
    for strategy_id in sorted({intent.strategy_id for intent in intents} | set(open_symbols_by_strategy)):
        sleeve = config.sleeves.get(strategy_id)
        current = gross_by_strategy.get(strategy_id, 0.0)
        added = approved_gross.get(strategy_id, 0.0)
        summaries[strategy_id] = StrategySummary(
            strategy_id=strategy_id,
            open_positions=len(open_symbols_by_strategy.get(strategy_id, set())),
            approved_new_positions=approved_count.get(strategy_id, 0),
            blocked_new_positions=blocked_count.get(strategy_id, 0),
            gross_exposure_current=current,
            gross_exposure_projected=current + added,
            max_concurrent_positions=sleeve.max_concurrent_positions if sleeve else None,
            max_gross_exposure_usd=sleeve.max_gross_exposure_usd if sleeve else None,
            max_daily_loss_usd=sleeve.max_daily_loss_usd if sleeve else None,
        )
    return summaries


def _build_portfolio_summary(
    *, positions: list[PositionState], approved: list[EntryIntent]
) -> dict[str, float | int]:
    gross_current = sum(_position_notional(position) for position in positions)
    gross_add = sum(_intent_notional(intent) for intent in approved)
    open_symbols = {position.symbol for position in positions}
    return {
        "gross_exposure_current": gross_current,
        "gross_exposure_projected": gross_current + gross_add,
        "open_positions": len(open_symbols),
        "approved_new_positions": len(approved),
    }
