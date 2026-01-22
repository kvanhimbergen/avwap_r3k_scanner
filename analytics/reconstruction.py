from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from typing import Iterable, Optional

from analytics.io.ledgers import LedgerParseError, parse_ledgers
from analytics.schemas import Fill, Lot, ReconstructionResult, Trade
from analytics.storage import write_reconstruction_json
from analytics.util import sort_fills


def _format_float(value: float) -> str:
    return repr(float(value))


def _format_optional_float(value: Optional[float]) -> str:
    if value is None:
        return ""
    return _format_float(value)


def _hash_payload(parts: Iterable[str]) -> str:
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_lot_id(lot: Lot) -> str:
    return _hash_payload(
        [
            lot.symbol,
            lot.side,
            lot.open_fill_id,
            lot.open_ts_utc,
            _format_float(lot.open_qty),
            _format_optional_float(lot.open_price),
            lot.venue,
            ",".join(lot.source_paths),
        ]
    )


def _build_trade_id(trade: Trade) -> str:
    return _hash_payload(
        [
            trade.symbol,
            trade.direction,
            trade.open_fill_id,
            trade.close_fill_id,
            trade.open_ts_utc,
            trade.close_ts_utc,
            _format_float(trade.qty),
            _format_optional_float(trade.open_price),
            _format_optional_float(trade.close_price),
            trade.venue,
        ]
    )


def _allocate_fee(total_fee: float, match_qty: float, total_qty: float) -> float:
    if total_qty <= 0:
        return 0.0
    return float(total_fee) * (float(match_qty) / float(total_qty))


def _notes_for_prices(open_price: Optional[float], close_price: Optional[float]) -> Optional[str]:
    notes: list[str] = []
    if open_price is None:
        notes.append("missing_price_open")
    if close_price is None:
        notes.append("missing_price_close")
    if notes:
        return ",".join(notes)
    return None


def _sort_trades(trades: Iterable[Trade]) -> list[Trade]:
    return sorted(
        trades,
        key=lambda trade: (
            trade.close_ts_utc,
            trade.symbol,
            trade.open_ts_utc,
            trade.open_fill_id,
            trade.close_fill_id,
            float(trade.qty),
            trade.trade_id,
        ),
    )


def _sort_lots(lots: Iterable[Lot]) -> list[Lot]:
    return sorted(
        lots,
        key=lambda lot: (
            lot.open_ts_utc,
            lot.symbol,
            lot.open_fill_id,
            float(lot.remaining_qty),
            lot.lot_id,
        ),
    )


@dataclass
class _LotState:
    open_fill: Fill
    remaining_qty: float
    lot_id: str
    source_paths: list[str]


def reconstruct_trades(fills: list[Fill], *, policy: str = "FIFO") -> ReconstructionResult:
    if policy != "FIFO":
        raise ValueError(f"unsupported policy: {policy}")

    sorted_fills = sort_fills(fills)
    warnings: list[str] = []
    trades: list[Trade] = []
    open_lots_by_key: dict[tuple[str, str, str], list[_LotState]] = {}

    for fill in sorted_fills:
        side = fill.side.lower()
        if side == "buy":
            if fill.qty <= 0:
                warnings.append(f"buy qty <= 0 for fill {fill.fill_id}; skipped")
                continue
            source_paths = sorted({fill.source_path})
            lot = Lot(
                lot_id="",
                symbol=fill.symbol,
                side="long",
                open_fill_id=fill.fill_id,
                open_ts_utc=fill.ts_utc,
                open_date_ny=fill.date_ny,
                open_qty=fill.qty,
                open_price=fill.price,
                remaining_qty=fill.qty,
                venue=fill.venue,
                source_paths=source_paths,
                strategy_id=fill.strategy_id,
                sleeve_id=fill.sleeve_id,
            )
            lot_id = _build_lot_id(lot)
            open_lot = _LotState(
                open_fill=fill,
                remaining_qty=fill.qty,
                lot_id=lot_id,
                source_paths=source_paths,
            )
            key = (fill.strategy_id, fill.sleeve_id, fill.symbol)
            open_lots_by_key.setdefault(key, []).append(open_lot)
            continue

        if side == "sell":
            if fill.qty <= 0:
                warnings.append(f"sell qty <= 0 for fill {fill.fill_id}; skipped")
                continue
            key = (fill.strategy_id, fill.sleeve_id, fill.symbol)
            lots = open_lots_by_key.get(key, [])
            if not lots:
                warnings.append(f"sell with no open lots for {fill.symbol}: {fill.fill_id}")
                continue
            qty_to_close = float(fill.qty)
            while qty_to_close > 0 and lots:
                lot_state = lots[0]
                match_qty = min(qty_to_close, lot_state.remaining_qty)
                open_fill = lot_state.open_fill
                notes = _notes_for_prices(open_fill.price, fill.price)
                fees = _allocate_fee(open_fill.fees, match_qty, open_fill.qty) + _allocate_fee(
                    fill.fees, match_qty, fill.qty
                )
                trade = Trade(
                    trade_id="",
                    symbol=fill.symbol,
                    direction="long",
                    open_fill_id=open_fill.fill_id,
                    close_fill_id=fill.fill_id,
                    open_ts_utc=open_fill.ts_utc,
                    close_ts_utc=fill.ts_utc,
                    open_date_ny=open_fill.date_ny,
                    close_date_ny=fill.date_ny,
                    qty=match_qty,
                    open_price=open_fill.price,
                    close_price=fill.price,
                    fees=fees,
                    venue=open_fill.venue,
                    notes=notes,
                    strategy_id=fill.strategy_id,
                    sleeve_id=fill.sleeve_id,
                )
                trade_id = _build_trade_id(trade)
                trades.append(
                    Trade(
                        trade_id=trade_id,
                        symbol=trade.symbol,
                        direction=trade.direction,
                        open_fill_id=trade.open_fill_id,
                        close_fill_id=trade.close_fill_id,
                        open_ts_utc=trade.open_ts_utc,
                        close_ts_utc=trade.close_ts_utc,
                        open_date_ny=trade.open_date_ny,
                        close_date_ny=trade.close_date_ny,
                        qty=trade.qty,
                        open_price=trade.open_price,
                        close_price=trade.close_price,
                        fees=trade.fees,
                        venue=trade.venue,
                        notes=trade.notes,
                        strategy_id=trade.strategy_id,
                        sleeve_id=trade.sleeve_id,
                    )
                )
                lot_state.remaining_qty -= match_qty
                qty_to_close -= match_qty
                if lot_state.remaining_qty <= 0:
                    lots.pop(0)
            if qty_to_close > 0:
                warnings.append(
                    f"sell exceeds open lots for {fill.symbol}: {fill.fill_id} remaining={qty_to_close}"
                )
            continue

        warnings.append(f"unsupported side '{fill.side}' for fill {fill.fill_id}")

    open_lots: list[Lot] = []
    for lots in open_lots_by_key.values():
        for lot_state in lots:
            open_fill = lot_state.open_fill
            open_lots.append(
                Lot(
                    lot_id=lot_state.lot_id,
                    symbol=open_fill.symbol,
                    side="long",
                    open_fill_id=open_fill.fill_id,
                    open_ts_utc=open_fill.ts_utc,
                    open_date_ny=open_fill.date_ny,
                    open_qty=open_fill.qty,
                    open_price=open_fill.price,
                    remaining_qty=lot_state.remaining_qty,
                    venue=open_fill.venue,
                    source_paths=lot_state.source_paths,
                    strategy_id=open_fill.strategy_id,
                    sleeve_id=open_fill.sleeve_id,
                )
            )

    return ReconstructionResult(
        trades=_sort_trades(trades),
        open_lots=_sort_lots(open_lots),
        warnings=warnings,
        source_metadata={},
    )


def _summarize(fills: list[Fill], result: ReconstructionResult) -> list[str]:
    lines: list[str] = []
    lines.append(f"fills: {len(fills)}")
    lines.append(f"trades: {len(result.trades)}")
    lines.append(f"open_lots: {len(result.open_lots)}")
    if fills:
        dates = sorted({fill.date_ny for fill in fills})
        date_range = dates[0] if len(dates) == 1 else f"{dates[0]}..{dates[-1]}"
        lines.append(f"date_ny range: {date_range}")
    else:
        lines.append("date_ny range: n/a")
    return lines


def _load_from_ledgers(
    *, dry_run_path: Optional[str], live_path: Optional[str]
) -> tuple[list[Fill], list[str], dict[str, str]]:
    ingest_results = parse_ledgers(dry_run_path=dry_run_path, live_path=live_path)
    fills: list[Fill] = []
    warnings: list[str] = []
    source_metadata: dict[str, str] = {}
    for idx, result in enumerate(ingest_results):
        fills.extend(result.fills)
        warnings.extend(result.warnings)
        prefix = result.source_metadata.get("ledger_type", f"ledger_{idx}")
        if not prefix:
            prefix = f"ledger_{idx}"
        for key, value in result.source_metadata.items():
            source_metadata[f"{prefix}.{key}"] = value
        source_metadata[f"{prefix}.count"] = str(len(result.fills))
    return sort_fills(fills), warnings, source_metadata


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Reconstruct trades from ledger fills")
    parser.add_argument("--dry-run-ledger", dest="dry_run_ledger", help="Path to dry-run ledger")
    parser.add_argument("--live-ledger", dest="live_ledger", help="Path to live ledger")
    parser.add_argument("--out", required=True, help="Output JSON path")
    args = parser.parse_args(argv)
    if not args.dry_run_ledger and not args.live_ledger:
        parser.error("at least one ledger path is required")
    try:
        fills, ingest_warnings, metadata = _load_from_ledgers(
            dry_run_path=args.dry_run_ledger, live_path=args.live_ledger
        )
        reconstruction = reconstruct_trades(fills)
    except LedgerParseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"unexpected error ({type(exc).__name__})", file=sys.stderr)
        return 2

    combined_warnings = ingest_warnings + reconstruction.warnings
    result = ReconstructionResult(
        trades=reconstruction.trades,
        open_lots=reconstruction.open_lots,
        warnings=combined_warnings,
        source_metadata=metadata,
    )
    write_reconstruction_json(args.out, result)
    for line in _summarize(fills, result):
        print(line)
    if result.warnings:
        print(f"warnings: {len(result.warnings)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
