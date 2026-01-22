from __future__ import annotations

import argparse
import sys
from typing import Optional

from analytics.io.ledgers import LedgerParseError, parse_ledgers
from analytics.metrics_storage import write_metrics_json
from analytics.reconstruction import reconstruct_trades
from analytics.schemas import CumulativeAggregate, DailyAggregate, Trade
from analytics.util import sort_fills


def _sort_trades_for_day(trades: list[Trade]) -> list[Trade]:
    return sorted(
        trades,
        key=lambda trade: (
            trade.close_ts_utc,
            trade.symbol,
            float(trade.qty),
            trade.trade_id,
        ),
    )


def _trade_realized_pnl(trade: Trade) -> float:
    if trade.direction == "short":
        return (float(trade.open_price) - float(trade.close_price)) * float(trade.qty)
    return (float(trade.close_price) - float(trade.open_price)) * float(trade.qty)


def _compute_partition_daily(trades: list[Trade]) -> list[DailyAggregate]:
    trades_by_date: dict[str, list[Trade]] = {}
    for trade in trades:
        trades_by_date.setdefault(trade.close_date_ny, []).append(trade)

    daily_aggregates: list[DailyAggregate] = []
    for date_ny in sorted(trades_by_date):
        day_trades = _sort_trades_for_day(trades_by_date[date_ny])
        symbols = sorted({trade.symbol for trade in day_trades})
        trade_count = len(day_trades)
        closed_qty = sum(float(trade.qty) for trade in day_trades)
        gross_notional_closed = sum(
            abs(float(trade.qty)) * (float(trade.close_price) if trade.close_price is not None else 0.0)
            for trade in day_trades
        )
        missing_price_trade_count = sum(
            1
            for trade in day_trades
            if trade.open_price is None or trade.close_price is None
        )
        fees_total = sum(float(trade.fees) for trade in day_trades)
        contains_short = any(trade.direction == "short" for trade in day_trades)
        warnings: list[str] = []
        if missing_price_trade_count:
            warnings.append("missing_price_in_day")
        if contains_short:
            warnings.append("contains_short_trades")

        realized_pnl: Optional[float]
        if missing_price_trade_count:
            realized_pnl = None
        else:
            realized_pnl = sum(_trade_realized_pnl(trade) for trade in day_trades)

        daily_aggregates.append(
            DailyAggregate(
                date_ny=date_ny,
                trade_count=trade_count,
                closed_qty=closed_qty,
                gross_notional_closed=gross_notional_closed,
                realized_pnl=realized_pnl,
                missing_price_trade_count=missing_price_trade_count,
                fees_total=fees_total,
                symbols_traded=symbols,
                warnings=warnings,
            )
        )

    return daily_aggregates


def compute_daily_aggregates(trades: list[Trade]) -> list[DailyAggregate]:
    trades_by_partition: dict[tuple[str, str], list[Trade]] = {}
    for trade in trades:
        key = (trade.strategy_id, trade.sleeve_id)
        trades_by_partition.setdefault(key, []).append(trade)

    merged_by_date: dict[str, dict[str, object]] = {}
    for partition_key in sorted(trades_by_partition):
        partition_trades = trades_by_partition[partition_key]
        for daily in _compute_partition_daily(partition_trades):
            entry = merged_by_date.setdefault(
                daily.date_ny,
                {
                    "trade_count": 0,
                    "closed_qty": 0.0,
                    "gross_notional_closed": 0.0,
                    "realized_pnl_total": 0.0,
                    "realized_pnl_known": True,
                    "missing_price_trade_count": 0,
                    "fees_total": 0.0,
                    "symbols_traded": set(),
                    "contains_short": False,
                },
            )
            entry["trade_count"] = int(entry["trade_count"]) + int(daily.trade_count)
            entry["closed_qty"] = float(entry["closed_qty"]) + float(daily.closed_qty)
            entry["gross_notional_closed"] = float(entry["gross_notional_closed"]) + float(
                daily.gross_notional_closed
            )
            entry["missing_price_trade_count"] = int(entry["missing_price_trade_count"]) + int(
                daily.missing_price_trade_count
            )
            entry["fees_total"] = float(entry["fees_total"]) + float(daily.fees_total)
            symbols = entry["symbols_traded"]
            if isinstance(symbols, set):
                symbols.update(daily.symbols_traded)
            entry["contains_short"] = bool(entry["contains_short"]) or (
                "contains_short_trades" in daily.warnings
            )
            if daily.realized_pnl is None:
                entry["realized_pnl_known"] = False
            if entry["realized_pnl_known"] and daily.realized_pnl is not None:
                entry["realized_pnl_total"] = float(entry["realized_pnl_total"]) + float(
                    daily.realized_pnl
                )

    daily_aggregates: list[DailyAggregate] = []
    for date_ny in sorted(merged_by_date):
        entry = merged_by_date[date_ny]
        realized_pnl = (
            float(entry["realized_pnl_total"]) if entry["realized_pnl_known"] else None
        )
        missing_price_trade_count = int(entry["missing_price_trade_count"])
        warnings: list[str] = []
        if missing_price_trade_count:
            warnings.append("missing_price_in_day")
        if entry["contains_short"]:
            warnings.append("contains_short_trades")
        symbols = entry["symbols_traded"]
        symbols_traded = sorted(symbols) if isinstance(symbols, set) else []
        daily_aggregates.append(
            DailyAggregate(
                date_ny=date_ny,
                trade_count=int(entry["trade_count"]),
                closed_qty=float(entry["closed_qty"]),
                gross_notional_closed=float(entry["gross_notional_closed"]),
                realized_pnl=realized_pnl,
                missing_price_trade_count=missing_price_trade_count,
                fees_total=float(entry["fees_total"]),
                symbols_traded=symbols_traded,
                warnings=warnings,
            )
        )

    return daily_aggregates


def compute_cumulative_aggregates(dailies: list[DailyAggregate]) -> list[CumulativeAggregate]:
    cumulative: list[CumulativeAggregate] = []
    trade_count = 0
    closed_qty = 0.0
    gross_notional_closed = 0.0
    missing_price_trade_count = 0
    fees_total = 0.0
    symbols_traded: set[str] = set()
    realized_pnl_total = 0.0
    realized_pnl_known = True

    for daily in sorted(dailies, key=lambda entry: entry.date_ny):
        trade_count += int(daily.trade_count)
        closed_qty += float(daily.closed_qty)
        gross_notional_closed += float(daily.gross_notional_closed)
        missing_price_trade_count += int(daily.missing_price_trade_count)
        fees_total += float(daily.fees_total)
        symbols_traded.update(daily.symbols_traded)
        if daily.realized_pnl is None:
            realized_pnl_known = False
        if realized_pnl_known and daily.realized_pnl is not None:
            realized_pnl_total += float(daily.realized_pnl)

        cumulative.append(
            CumulativeAggregate(
                through_date_ny=daily.date_ny,
                trade_count=trade_count,
                closed_qty=closed_qty,
                gross_notional_closed=gross_notional_closed,
                realized_pnl=realized_pnl_total if realized_pnl_known else None,
                missing_price_trade_count=missing_price_trade_count,
                fees_total=fees_total,
                symbols_traded=sorted(symbols_traded),
            )
        )

    return cumulative


def _load_from_ledgers(
    *, dry_run_path: Optional[str], live_path: Optional[str]
) -> tuple[list[Trade], list[str]]:
    ingest_results = parse_ledgers(dry_run_path=dry_run_path, live_path=live_path)
    fills = []
    warnings: list[str] = []
    for result in ingest_results:
        fills.extend(result.fills)
        warnings.extend(result.warnings)
    reconstruction = reconstruct_trades(sort_fills(fills))
    warnings.extend(reconstruction.warnings)
    return reconstruction.trades, warnings


def _summarize(trades: list[Trade], dailies: list[DailyAggregate]) -> list[str]:
    lines: list[str] = []
    lines.append(f"trades: {len(trades)}")
    if dailies:
        dates = [daily.date_ny for daily in dailies]
        date_range = dates[0] if len(dates) == 1 else f"{dates[0]}..{dates[-1]}"
        lines.append(f"date_ny range: {date_range}")
        realized_known = all(daily.realized_pnl is not None for daily in dailies)
        lines.append(f"realized_pnl fully known: {'yes' if realized_known else 'no'}")
    else:
        lines.append("date_ny range: n/a")
        lines.append("realized_pnl fully known: yes")
    return lines


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compute daily and cumulative trade aggregates")
    parser.add_argument("--dry-run-ledger", dest="dry_run_ledger", help="Path to dry-run ledger")
    parser.add_argument("--live-ledger", dest="live_ledger", help="Path to live ledger")
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args(argv)
    if not args.dry_run_ledger and not args.live_ledger:
        parser.error("at least one ledger path is required")
    try:
        trades, warnings = _load_from_ledgers(
            dry_run_path=args.dry_run_ledger, live_path=args.live_ledger
        )
        dailies = compute_daily_aggregates(trades)
        cumulative = compute_cumulative_aggregates(dailies)
    except LedgerParseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"unexpected error ({type(exc).__name__})", file=sys.stderr)
        return 2

    write_metrics_json(args.out, dailies=dailies, cumulative=cumulative)
    for line in _summarize(trades, dailies):
        print(line)
    if warnings:
        print(f"warnings: {len(warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
