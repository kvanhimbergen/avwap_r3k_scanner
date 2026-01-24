from __future__ import annotations

import hashlib
from typing import Iterable

from analytics.schemas import ExitEvent, ExitReconstructionResult, ExitTrade
from analytics.util import date_ny, parse_timestamp


def _format_float(value: float) -> str:
    return repr(float(value))


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return _format_float(value)


def _hash_payload(parts: Iterable[str]) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_trade_id(event: ExitEvent) -> str:
    return _hash_payload(
        [
            event.symbol,
            event.entry_ts_utc or "",
            event.exit_ts_utc or "",
            _format_optional_float(event.entry_price),
            _format_optional_float(event.price),
            _format_optional_float(event.qty),
            event.position_id or "",
        ]
    )


def reconstruct_exit_trades(events: list[ExitEvent]) -> ExitReconstructionResult:
    trades: list[ExitTrade] = []
    warnings: list[str] = []

    for event in events:
        if event.event_type != "EXIT_FILLED":
            continue
        if event.entry_ts_utc is None:
            warnings.append(f"exit event missing entry_ts_utc: {event.event_id}")
            continue
        if event.exit_ts_utc is None:
            warnings.append(f"exit event missing exit_ts_utc: {event.event_id}")
            continue

        entry_dt = parse_timestamp(event.entry_ts_utc, source_path=event.event_id, entry_index=0)
        exit_dt = parse_timestamp(event.exit_ts_utc, source_path=event.event_id, entry_index=0)

        trade_id = event.trade_id or _build_trade_id(event)
        trades.append(
            ExitTrade(
                trade_id=trade_id,
                position_id=event.position_id,
                symbol=event.symbol,
                direction="long",
                entry_ts_utc=event.entry_ts_utc,
                exit_ts_utc=event.exit_ts_utc,
                entry_date_ny=event.entry_date_ny or date_ny(entry_dt),
                exit_date_ny=event.exit_date_ny or date_ny(exit_dt),
                qty=float(event.qty or 0.0),
                entry_price=event.entry_price,
                exit_price=event.price,
                stop_price=event.stop_price,
                stop_basis=event.stop_basis,
                reason=event.reason,
                source=event.source,
                strategy_id=event.strategy_id,
                sleeve_id=event.sleeve_id,
            )
        )

    trades_sorted = sorted(
        trades,
        key=lambda trade: (
            trade.exit_ts_utc,
            trade.symbol,
            trade.entry_ts_utc,
            trade.trade_id,
        ),
    )

    return ExitReconstructionResult(
        trades=trades_sorted,
        warnings=warnings,
        source_metadata={},
    )
