from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from analytics.schemas import Lot, PortfolioPosition, PortfolioSnapshot, Trade
from execution_v2.strategy_registry import DEFAULT_STRATEGY_ID

SCHEMA_VERSION = 2
DEFAULT_VOLATILITY_WINDOW = 5


@dataclass(frozen=True)
class DailyRealized:
    date_ny: str
    realized_pnl: Optional[float]
    fees_total: float
    trade_count: int
    missing_price_trade_count: int


def _trade_realized_pnl_net_fees(trade: Trade) -> Optional[float]:
    if trade.open_price is None or trade.close_price is None:
        return None
    open_price = float(trade.open_price)
    close_price = float(trade.close_price)
    qty = float(trade.qty)
    if trade.direction == "short":
        pnl = (open_price - close_price) * qty
    else:
        pnl = (close_price - open_price) * qty
    return pnl - float(trade.fees)


def compute_daily_realized(trades: list[Trade]) -> list[DailyRealized]:
    by_date: dict[str, list[Trade]] = {}
    for trade in trades:
        by_date.setdefault(trade.close_date_ny, []).append(trade)

    dailies: list[DailyRealized] = []
    for date_ny in sorted(by_date):
        day_trades = sorted(
            by_date[date_ny],
            key=lambda trade: (trade.close_ts_utc, trade.symbol, trade.trade_id),
        )
        missing_price_trade_count = 0
        pnl_total = 0.0
        realized_known = True
        fees_total = 0.0
        for trade in day_trades:
            fees_total += float(trade.fees)
            pnl = _trade_realized_pnl_net_fees(trade)
            if pnl is None:
                realized_known = False
                missing_price_trade_count += 1
                continue
            pnl_total += pnl

        realized_pnl = pnl_total if realized_known else None
        dailies.append(
            DailyRealized(
                date_ny=date_ny,
                realized_pnl=realized_pnl,
                fees_total=fees_total,
                trade_count=len(day_trades),
                missing_price_trade_count=missing_price_trade_count,
            )
        )
    return dailies


def compute_symbol_contributions(trades: list[Trade]) -> list[dict[str, object]]:
    per_symbol: dict[str, dict[str, object]] = {}
    for trade in trades:
        entry = per_symbol.setdefault(
            trade.symbol,
            {
                "realized_pnl_total": 0.0,
                "realized_pnl_known": True,
                "fees_total": 0.0,
                "trade_count": 0,
                "missing_price_trade_count": 0,
            },
        )
        entry["trade_count"] = int(entry["trade_count"]) + 1
        entry["fees_total"] = float(entry["fees_total"]) + float(trade.fees)
        pnl = _trade_realized_pnl_net_fees(trade)
        if pnl is None:
            entry["realized_pnl_known"] = False
            entry["missing_price_trade_count"] = int(entry["missing_price_trade_count"]) + 1
        if entry["realized_pnl_known"] and pnl is not None:
            entry["realized_pnl_total"] = float(entry["realized_pnl_total"]) + pnl

    rows: list[dict[str, object]] = []
    for symbol in sorted(per_symbol):
        entry = per_symbol[symbol]
        realized_pnl = (
            float(entry["realized_pnl_total"]) if entry["realized_pnl_known"] else None
        )
        rows.append(
            {
                "symbol": symbol,
                "realized_pnl": realized_pnl,
                "fees_total": float(entry["fees_total"]),
                "trade_count": int(entry["trade_count"]),
                "missing_price_trade_count": int(entry["missing_price_trade_count"]),
            }
        )
    return rows


def compute_strategy_realized(trades: list[Trade]) -> dict[str, dict[str, object]]:
    per_strategy: dict[str, dict[str, object]] = {}
    for trade in trades:
        strategy_id = trade.strategy_id or DEFAULT_STRATEGY_ID
        entry = per_strategy.setdefault(
            strategy_id,
            {
                "realized_pnl_total": 0.0,
                "realized_pnl_known": True,
                "fees_total": 0.0,
                "trade_count": 0,
                "missing_price_trade_count": 0,
            },
        )
        entry["trade_count"] = int(entry["trade_count"]) + 1
        entry["fees_total"] = float(entry["fees_total"]) + float(trade.fees)
        pnl = _trade_realized_pnl_net_fees(trade)
        if pnl is None:
            entry["realized_pnl_known"] = False
            entry["missing_price_trade_count"] = int(entry["missing_price_trade_count"]) + 1
        if entry["realized_pnl_known"] and pnl is not None:
            entry["realized_pnl_total"] = float(entry["realized_pnl_total"]) + pnl
    realized: dict[str, dict[str, object]] = {}
    for strategy_id in sorted(per_strategy):
        entry = per_strategy[strategy_id]
        realized_pnl = (
            float(entry["realized_pnl_total"]) if entry["realized_pnl_known"] else None
        )
        realized[strategy_id] = {
            "realized_pnl": realized_pnl,
            "fees_total": float(entry["fees_total"]),
            "trade_count": int(entry["trade_count"]),
            "missing_price_trade_count": int(entry["missing_price_trade_count"]),
        }
    return realized


def compute_strategy_unrealized(
    positions: list[PortfolioPosition],
) -> dict[str, dict[str, object]]:
    per_strategy: dict[str, dict[str, object]] = {}
    for position in positions:
        strategy_id = position.strategy_id or DEFAULT_STRATEGY_ID
        entry = per_strategy.setdefault(
            strategy_id,
            {
                "unrealized_pnl_total": 0.0,
                "unrealized_pnl_known": True,
                "position_count": 0,
                "missing_price_position_count": 0,
            },
        )
        entry["position_count"] = int(entry["position_count"]) + 1
        if position.mark_price is None or position.avg_price is None:
            entry["unrealized_pnl_known"] = False
            entry["missing_price_position_count"] = int(
                entry["missing_price_position_count"]
            ) + 1
            continue
        pnl = (float(position.mark_price) - float(position.avg_price)) * float(position.qty)
        if entry["unrealized_pnl_known"]:
            entry["unrealized_pnl_total"] = float(entry["unrealized_pnl_total"]) + pnl
    unrealized: dict[str, dict[str, object]] = {}
    for strategy_id in sorted(per_strategy):
        entry = per_strategy[strategy_id]
        unrealized_pnl = (
            float(entry["unrealized_pnl_total"]) if entry["unrealized_pnl_known"] else None
        )
        unrealized[strategy_id] = {
            "unrealized_pnl": unrealized_pnl,
            "position_count": int(entry["position_count"]),
            "missing_price_position_count": int(entry["missing_price_position_count"]),
        }
    return unrealized


def compute_strategy_exposures(
    positions: list[PortfolioPosition],
) -> dict[str, dict[str, float | int]]:
    per_strategy: dict[str, dict[str, object]] = {}
    for position in positions:
        strategy_id = position.strategy_id or DEFAULT_STRATEGY_ID
        entry = per_strategy.setdefault(
            strategy_id,
            {"gross_exposure": 0.0, "net_exposure": 0.0, "position_count": 0},
        )
        entry["gross_exposure"] = float(entry["gross_exposure"]) + abs(float(position.notional))
        entry["net_exposure"] = float(entry["net_exposure"]) + float(position.notional)
        entry["position_count"] = int(entry["position_count"]) + 1
    exposures: dict[str, dict[str, float | int]] = {}
    for strategy_id in sorted(per_strategy):
        entry = per_strategy[strategy_id]
        exposures[strategy_id] = {
            "gross_exposure": float(entry["gross_exposure"]),
            "net_exposure": float(entry["net_exposure"]),
            "position_count": int(entry["position_count"]),
        }
    return exposures


def compute_strategy_drawdown(
    trades: list[Trade], *, starting_capital: Optional[float]
) -> dict[str, dict[str, object]]:
    by_strategy: dict[str, list[Trade]] = {}
    for trade in trades:
        strategy_id = trade.strategy_id or DEFAULT_STRATEGY_ID
        by_strategy.setdefault(strategy_id, []).append(trade)
    drawdowns: dict[str, dict[str, object]] = {}
    for strategy_id in sorted(by_strategy):
        daily_realized = compute_daily_realized(by_strategy[strategy_id])
        drawdowns[strategy_id] = compute_drawdown(
            daily_realized, starting_capital=starting_capital
        )
    return drawdowns


def compute_drawdown(
    daily_realized: list[DailyRealized], *, starting_capital: Optional[float]
) -> dict[str, object]:
    if not daily_realized:
        return {
            "series": [],
            "max_drawdown": None,
            "reason_codes": ["no_realized_pnl"],
        }
    if any(entry.realized_pnl is None for entry in daily_realized):
        return {
            "series": [],
            "max_drawdown": None,
            "reason_codes": ["realized_pnl_unavailable"],
        }

    equity = float(starting_capital or 0.0)
    peak = equity
    series: list[dict[str, object]] = []
    max_drawdown = 0.0
    for entry in sorted(daily_realized, key=lambda item: item.date_ny):
        equity += float(entry.realized_pnl or 0.0)
        if equity > peak:
            peak = equity
        drawdown = 0.0 if peak == 0 else (equity - peak) / peak
        series.append({"date_ny": entry.date_ny, "drawdown": drawdown})
        max_drawdown = min(max_drawdown, drawdown)

    return {
        "series": series,
        "max_drawdown": max_drawdown,
        "reason_codes": [],
    }


def _stddev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def compute_rolling_volatility(
    daily_realized: list[DailyRealized],
    *,
    starting_capital: Optional[float],
    window: int = DEFAULT_VOLATILITY_WINDOW,
) -> dict[str, object]:
    if not daily_realized:
        return {"window": window, "series": [], "reason_codes": ["no_realized_pnl"]}
    if any(entry.realized_pnl is None for entry in daily_realized):
        return {
            "window": window,
            "series": [],
            "reason_codes": ["realized_pnl_unavailable"],
        }
    if starting_capital is None or starting_capital <= 0:
        return {
            "window": window,
            "series": [],
            "reason_codes": ["starting_capital_unavailable"],
        }

    series: list[dict[str, object]] = []
    returns: list[float] = []
    equity = float(starting_capital)
    for entry in sorted(daily_realized, key=lambda item: item.date_ny):
        if equity == 0:
            return {
                "window": window,
                "series": [],
                "reason_codes": ["equity_zero"],
            }
        daily_return = float(entry.realized_pnl or 0.0) / equity
        returns.append(daily_return)
        volatility = None
        if len(returns) >= window:
            volatility = _stddev(returns[-window:])
        series.append({"date_ny": entry.date_ny, "volatility": volatility})
        equity += float(entry.realized_pnl or 0.0)

    return {"window": window, "series": series, "reason_codes": []}


def build_positions(
    open_lots: list[Lot], *, price_map: Optional[dict[str, float]] = None
) -> tuple[list[PortfolioPosition], list[str]]:
    price_map = price_map or {}
    by_symbol: dict[str, dict[str, object]] = {}
    reason_codes: list[str] = []
    for lot in open_lots:
        entry = by_symbol.setdefault(
            lot.symbol,
            {
                "qty": 0.0,
                "cost_total": 0.0,
                "price_missing": False,
                "strategy_id": lot.strategy_id,
                "strategy_mixed": False,
            },
        )
        if entry["strategy_id"] != lot.strategy_id:
            entry["strategy_mixed"] = True
        qty = float(lot.remaining_qty)
        entry["qty"] = float(entry["qty"]) + qty
        if lot.open_price is None:
            entry["price_missing"] = True
        else:
            entry["cost_total"] = float(entry["cost_total"]) + qty * float(lot.open_price)

    positions: list[PortfolioPosition] = []
    for symbol in sorted(by_symbol):
        entry = by_symbol[symbol]
        qty = float(entry["qty"])
        avg_price = None
        if qty != 0 and not entry["price_missing"]:
            avg_price = float(entry["cost_total"]) / qty
        elif entry["price_missing"]:
            reason_codes.append("position_open_price_missing")
        mark_price = price_map.get(symbol)
        if mark_price is None:
            reason_codes.append("position_mark_price_missing")
        notional_price = mark_price if mark_price is not None else avg_price
        if notional_price is None:
            reason_codes.append("position_price_missing")
            notional_price = 0.0
        notional = qty * float(notional_price)
        strategy_id = entry["strategy_id"]
        if entry["strategy_mixed"]:
            reason_codes.append("position_strategy_mixed")
            strategy_id = "MULTI"
        positions.append(
            PortfolioPosition(
                strategy_id=strategy_id,
                symbol=symbol,
                qty=qty,
                avg_price=avg_price,
                mark_price=mark_price,
                notional=notional,
            )
        )

    return positions, sorted(set(reason_codes))


def compute_exposures(positions: list[PortfolioPosition]) -> tuple[float, float]:
    gross_exposure = sum(abs(float(pos.notional)) for pos in positions)
    net_exposure = sum(float(pos.notional) for pos in positions)
    return gross_exposure, net_exposure


def compute_unrealized_pnl(
    positions: list[PortfolioPosition],
) -> tuple[Optional[float], list[str]]:
    if not positions:
        return 0.0, []
    if any(pos.mark_price is None or pos.avg_price is None for pos in positions):
        return None, ["mark_price_unavailable"]
    pnl = sum((float(pos.mark_price) - float(pos.avg_price)) * float(pos.qty) for pos in positions)
    return pnl, []


def build_portfolio_snapshot(
    *,
    date_ny: str,
    run_id: str,
    trades: Optional[list[Trade]] = None,
    open_lots: Optional[list[Lot]] = None,
    starting_capital: Optional[float] = None,
    ending_capital: Optional[float] = None,
    price_map: Optional[dict[str, float]] = None,
    ledger_paths: Optional[list[str]] = None,
    input_hashes: Optional[dict[str, str]] = None,
    extra_reason_codes: Optional[list[str]] = None,
    volatility_window: int = DEFAULT_VOLATILITY_WINDOW,
) -> PortfolioSnapshot:
    reason_codes: list[str] = []
    trades = trades or []
    open_lots = open_lots or []
    if not trades:
        reason_codes.append("trades_missing")
    if not open_lots:
        reason_codes.append("open_lots_missing")

    daily_realized = compute_daily_realized(trades)
    daily_realized_for_date = next(
        (entry for entry in daily_realized if entry.date_ny == date_ny), None
    )
    realized_reason_codes: list[str] = []
    realized_pnl = None
    fees_total = None
    if daily_realized_for_date is None:
        realized_reason_codes.append("realized_pnl_date_missing")
    else:
        realized_pnl = daily_realized_for_date.realized_pnl
        fees_total = daily_realized_for_date.fees_total
        if realized_pnl is None:
            realized_reason_codes.append("realized_pnl_unavailable")

    positions, position_reason_codes = build_positions(open_lots, price_map=price_map)
    unrealized_pnl, unrealized_reason_codes = compute_unrealized_pnl(positions)
    gross_exposure, net_exposure = compute_exposures(positions)

    drawdown = compute_drawdown(daily_realized, starting_capital=starting_capital)
    rolling_volatility = compute_rolling_volatility(
        daily_realized, starting_capital=starting_capital, window=volatility_window
    )
    contributions = compute_symbol_contributions(trades)
    strategy_exposures = compute_strategy_exposures(positions)
    strategy_realized = compute_strategy_realized(trades)
    strategy_unrealized = compute_strategy_unrealized(positions)
    strategy_drawdown = compute_strategy_drawdown(
        trades, starting_capital=starting_capital
    )
    strategy_attribution = _build_strategy_attribution(
        strategy_exposures=strategy_exposures,
        strategy_realized=strategy_realized,
        strategy_unrealized=strategy_unrealized,
        strategy_drawdown=strategy_drawdown,
        gross_exposure=gross_exposure,
        net_exposure=net_exposure,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
    )

    pnl_reason_codes = sorted(
        set(realized_reason_codes + unrealized_reason_codes + position_reason_codes)
    )

    combined_reason_codes = sorted(set(reason_codes + (extra_reason_codes or [])))
    provenance = {
        "ledger_paths": sorted(set(ledger_paths or [])),
        "input_hashes": dict(sorted((input_hashes or {}).items())),
        "reason_codes": combined_reason_codes,
    }

    strategy_ids = sorted(
        {
            *(trade.strategy_id for trade in trades),
            *(lot.strategy_id for lot in open_lots),
        }
    )
    if not strategy_ids:
        strategy_ids = [DEFAULT_STRATEGY_ID]

    return PortfolioSnapshot(
        schema_version=SCHEMA_VERSION,
        date_ny=date_ny,
        run_id=run_id,
        strategy_ids=strategy_ids,
        capital={"starting": starting_capital, "ending": ending_capital},
        gross_exposure=gross_exposure,
        net_exposure=net_exposure,
        positions=positions,
        pnl={
            "realized": realized_pnl,
            "unrealized": unrealized_pnl,
            "fees_total": fees_total,
            "reason_codes": pnl_reason_codes,
        },
        metrics={
            "drawdown": drawdown,
            "rolling_volatility": rolling_volatility,
            "contributions": contributions,
            "strategy_attribution": strategy_attribution,
        },
        provenance=provenance,
    )


def size_position(
    *,
    capital: float,
    risk_budget: float,
    price: float,
    max_notional: Optional[float] = None,
) -> dict[str, object]:
    reason_codes: list[str] = []
    if capital <= 0:
        return {"qty": 0.0, "notional": 0.0, "reason_codes": ["capital_unavailable"]}
    if price <= 0:
        return {"qty": 0.0, "notional": 0.0, "reason_codes": ["price_unavailable"]}
    if risk_budget <= 0:
        return {"qty": 0.0, "notional": 0.0, "reason_codes": ["risk_budget_unavailable"]}

    target_notional = float(capital) * float(risk_budget)
    if max_notional is not None and target_notional > max_notional:
        target_notional = float(max_notional)
        reason_codes.append("max_notional_capped")
    qty = target_notional / float(price)
    return {"qty": qty, "notional": qty * float(price), "reason_codes": reason_codes}


def evaluate_allocation_guardrails(
    *,
    positions: list[PortfolioPosition],
    capital: Optional[float],
    concentration_limit: float,
) -> dict[str, object]:
    violations: list[dict[str, object]] = []
    if capital is None or capital <= 0:
        violations.append(
            {"code": "capital_unavailable", "message": "capital required for concentration"}
        )
    else:
        for position in positions:
            concentration = abs(float(position.notional)) / float(capital)
            if concentration > concentration_limit:
                violations.append(
                    {
                        "code": "concentration_exceeded",
                        "symbol": position.symbol,
                        "concentration": concentration,
                        "limit": concentration_limit,
                    }
                )

    correlation = {
        "status": "placeholder",
        "reason": "correlation_model_unavailable",
        "passed": True,
    }

    return {
        "passed": len(violations) == 0,
        "violations": violations,
        "correlation": correlation,
    }


def _build_strategy_attribution(
    *,
    strategy_exposures: dict[str, dict[str, float | int]],
    strategy_realized: dict[str, dict[str, object]],
    strategy_unrealized: dict[str, dict[str, object]],
    strategy_drawdown: dict[str, dict[str, object]],
    gross_exposure: float,
    net_exposure: float,
    realized_pnl: Optional[float],
    unrealized_pnl: Optional[float],
) -> dict[str, object]:
    by_strategy: dict[str, dict[str, object]] = {}
    strategy_ids = sorted(
        {
            *strategy_exposures.keys(),
            *strategy_realized.keys(),
            *strategy_unrealized.keys(),
            *strategy_drawdown.keys(),
        }
    )
    for strategy_id in strategy_ids:
        exposure = strategy_exposures.get(strategy_id, {})
        realized = strategy_realized.get(strategy_id, {})
        unrealized = strategy_unrealized.get(strategy_id, {})
        drawdown = strategy_drawdown.get(strategy_id, {})
        by_strategy[strategy_id] = {
            "exposure": exposure,
            "pnl": {
                "realized": realized.get("realized_pnl"),
                "unrealized": unrealized.get("unrealized_pnl"),
                "fees_total": realized.get("fees_total"),
                "trade_count": realized.get("trade_count"),
                "missing_price_trade_count": realized.get("missing_price_trade_count"),
                "missing_price_position_count": unrealized.get("missing_price_position_count"),
            },
            "drawdown": drawdown,
        }

    exposure_gross_total = sum(
        float(entry.get("gross_exposure", 0.0)) for entry in strategy_exposures.values()
    )
    exposure_net_total = sum(
        float(entry.get("net_exposure", 0.0)) for entry in strategy_exposures.values()
    )
    pnl_realized_total = _sum_if_known(strategy_realized, "realized_pnl")
    pnl_unrealized_total = _sum_if_known(strategy_unrealized, "unrealized_pnl")

    reconciliation = {
        "exposure": {
            "gross_total": exposure_gross_total,
            "net_total": exposure_net_total,
            "portfolio_gross": gross_exposure,
            "portfolio_net": net_exposure,
            "gross_delta": exposure_gross_total - gross_exposure,
            "net_delta": exposure_net_total - net_exposure,
        },
        "pnl": {
            "realized_total": pnl_realized_total,
            "unrealized_total": pnl_unrealized_total,
            "portfolio_realized": realized_pnl,
            "portfolio_unrealized": unrealized_pnl,
            "realized_delta": _delta(pnl_realized_total, realized_pnl),
            "unrealized_delta": _delta(pnl_unrealized_total, unrealized_pnl),
        },
    }

    return {
        "by_strategy": by_strategy,
        "reconciliation": reconciliation,
    }


def _sum_if_known(values: dict[str, dict[str, object]], key: str) -> Optional[float]:
    if not values:
        return 0.0
    total = 0.0
    for entry in values.values():
        value = entry.get(key)
        if value is None:
            return None
        total += float(value)
    return total


def _delta(total: Optional[float], portfolio_value: Optional[float]) -> Optional[float]:
    if total is None or portfolio_value is None:
        return None
    return float(total) - float(portfolio_value)
