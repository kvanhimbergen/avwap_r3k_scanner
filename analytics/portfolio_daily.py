from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from analytics.broker_adapter import BrokerAdapter
from analytics.portfolio import build_portfolio_snapshot
from analytics.portfolio_storage import write_portfolio_snapshot_artifact
from analytics.reconstruction import reconstruct_trades
from analytics.schemas import BrokerPosition, PortfolioSnapshot
from analytics.storage import parse_reconstruction_json
from analytics.util import normalize_symbol
from analytics.io.ledgers import LedgerParseError, parse_ledgers


@dataclass(frozen=True)
class DailySnapshotResult:
    snapshot: PortfolioSnapshot
    output_path: str


def _build_price_map_from_broker(positions: list[BrokerPosition]) -> tuple[dict[str, float], list[str]]:
    price_map: dict[str, float] = {}
    reason_codes: list[str] = []
    for position in positions:
        if position.last_price is None:
            reason_codes.append("broker_last_price_missing")
            continue
        symbol = normalize_symbol(position.symbol)
        if not symbol:
            continue
        price_map[symbol] = float(position.last_price)
    return price_map, sorted(set(reason_codes))


def _load_reconstruction(
    *,
    reconstruction_path: Optional[str],
    dry_run_ledger: Optional[str],
    live_ledger: Optional[str],
) -> tuple[list, list, list[str]]:
    reason_codes: list[str] = []
    if reconstruction_path:
        reconstruction = parse_reconstruction_json(reconstruction_path)
        return reconstruction.trades, reconstruction.open_lots, reason_codes
    if dry_run_ledger or live_ledger:
        try:
            results = parse_ledgers(dry_run_path=dry_run_ledger, live_path=live_ledger)
        except LedgerParseError as exc:
            raise ValueError(str(exc)) from exc
        fills = []
        for result in results:
            fills.extend(result.fills)
        reconstruction = reconstruct_trades(fills)
        return reconstruction.trades, reconstruction.open_lots, reason_codes
    reason_codes.append("reconstruction_missing")
    return [], [], reason_codes


def build_daily_portfolio_snapshot(
    *,
    date_ny: str,
    run_id: str,
    reconstruction_path: Optional[str] = None,
    dry_run_ledger: Optional[str] = None,
    live_ledger: Optional[str] = None,
    price_map: Optional[dict[str, float]] = None,
    broker_positions: Optional[list[BrokerPosition]] = None,
    broker_adapter: Optional[BrokerAdapter] = None,
    ledger_paths: Optional[list[str]] = None,
    input_hashes: Optional[dict[str, str]] = None,
) -> PortfolioSnapshot:
    trades, open_lots, reconstruction_reason = _load_reconstruction(
        reconstruction_path=reconstruction_path,
        dry_run_ledger=dry_run_ledger,
        live_ledger=live_ledger,
    )
    reason_codes = list(reconstruction_reason)

    positions = broker_positions
    if positions is None and broker_adapter is not None:
        positions = broker_adapter.fetch_positions()
    if positions is None:
        reason_codes.append("broker_positions_missing")
    if price_map is None and positions:
        derived_prices, broker_price_codes = _build_price_map_from_broker(positions)
        price_map = derived_prices
        reason_codes.extend(broker_price_codes)

    snapshot = build_portfolio_snapshot(
        date_ny=date_ny,
        run_id=run_id,
        trades=trades,
        open_lots=open_lots,
        price_map=price_map,
        ledger_paths=ledger_paths,
        input_hashes=input_hashes,
        extra_reason_codes=sorted(set(reason_codes)),
    )
    return snapshot


def write_daily_portfolio_snapshot(
    snapshot: PortfolioSnapshot, *, base_dir: str = "analytics/artifacts/portfolio_snapshots"
) -> DailySnapshotResult:
    output_path = write_portfolio_snapshot_artifact(snapshot, base_dir=base_dir)
    return DailySnapshotResult(snapshot=snapshot, output_path=output_path)
