"""ShadowBook — synthetic portfolio tracker used in dry-run + backtest.

Starts at a configurable cash balance (default $230K), takes daily
target weights, applies trades at the next close, and tracks the equity
curve. Used by:
- backtests/raec_v6_portfolio_bt.py (offline replay)
- strategies.raec_v6.coordinator (live dry-run parallel to V3/V4/V5)

The book has no notion of fractional shares — orders execute as
exact-percent-of-equity for clean equity curve math. Slippage is a
configurable basis-point haircut applied per trade. Per-symbol prices
are passed in by the caller for each step.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class TradeRecord:
    asof: date
    symbol: str
    side: str  # "BUY" or "SELL"
    notional: float
    pre_weight: float
    target_weight: float


@dataclass(frozen=True)
class StepResult:
    asof: date
    equity: float
    cash: float
    positions: dict[str, float]  # symbol -> notional
    weights: dict[str, float]    # symbol -> share of equity (after step)
    daily_return: float          # equity-pct vs prior step (0 on day 1)
    trades: tuple[TradeRecord, ...]


@dataclass
class ShadowBook:
    """Mutable in-memory book used during a backtest run.

    History accumulates internally as records — use to_history() to extract.
    """

    starting_cash: float = 230_000.0
    slippage_bps: float = 5.0  # one-sided; applied to traded notional

    equity_curve: list[float] = field(default_factory=list)
    cash_curve: list[float] = field(default_factory=list)
    positions: dict[str, float] = field(default_factory=dict)
    daily_returns: list[float] = field(default_factory=list)
    asof_history: list[date] = field(default_factory=list)
    trade_log: list[TradeRecord] = field(default_factory=list)

    @property
    def cash(self) -> float:
        return self.cash_curve[-1] if self.cash_curve else self.starting_cash

    @property
    def equity(self) -> float:
        return self.equity_curve[-1] if self.equity_curve else self.starting_cash

    def step(
        self,
        *,
        asof: date,
        target_weights: Mapping[str, float],
        close_prices: Mapping[str, float],
        min_trade_pct: float = 0.5,
    ) -> StepResult:
        """Advance the book one day:
        1) Mark-to-market existing positions at close.
        2) Apply trades from current → target weights.
        3) Record equity, daily return, positions.
        """
        # Step 1: Mark-to-market via per-symbol close pct change since prior step.
        # We track notional (dollar) positions. To MTM, we need per-day close *changes*,
        # which the caller provides via cumulative close_prices. We store the last
        # known close per symbol internally.
        if not hasattr(self, "_last_close"):
            self._last_close: dict[str, float] = {}
        prior_positions = dict(self.positions)
        marked: dict[str, float] = {}
        for sym, notional in prior_positions.items():
            prev_close = self._last_close.get(sym)
            curr_close = close_prices.get(sym)
            if prev_close is None or curr_close is None or prev_close <= 0:
                marked[sym] = notional  # no info → leave unchanged
                continue
            marked[sym] = notional * (curr_close / prev_close)
        # Update last-known closes for all provided symbols (so a symbol we'll
        # buy today has a reference price for the next MTM).
        for sym, px in close_prices.items():
            if px > 0:
                self._last_close[sym] = px

        cash = self.cash
        equity_pre_trade = cash + sum(marked.values())

        # Step 2: Apply trades to move toward target weights.
        # Compute target dollars per symbol = target_weight * equity_pre_trade.
        target_dollars: dict[str, float] = {
            s.upper(): w * equity_pre_trade for s, w in target_weights.items()
        }
        # Build a unified symbol set: prior positions ∪ target positions
        all_syms = set(marked) | set(target_dollars)
        trades: list[TradeRecord] = []
        for sym in all_syms:
            current = marked.get(sym, 0.0)
            target = target_dollars.get(sym, 0.0)
            delta = target - current
            # min_trade filter (in pct of equity)
            if equity_pre_trade > 0 and abs(delta) / equity_pre_trade < (min_trade_pct / 100):
                continue
            side = "BUY" if delta > 0 else "SELL"
            slip = abs(delta) * (self.slippage_bps / 10_000)
            cash -= delta + slip  # buy: cash decreases by delta+slip; sell: increases by |delta|-slip
            marked[sym] = current + delta
            pre_w = current / equity_pre_trade if equity_pre_trade > 0 else 0.0
            tgt_w = target / equity_pre_trade if equity_pre_trade > 0 else 0.0
            tr = TradeRecord(
                asof=asof,
                symbol=sym,
                side=side,
                notional=abs(delta),
                pre_weight=pre_w,
                target_weight=tgt_w,
            )
            trades.append(tr)

        # Drop zeroed positions.
        positions_after = {s: v for s, v in marked.items() if abs(v) > 1e-6}
        equity_post = cash + sum(positions_after.values())

        # Step 3: Record + return.
        prior_equity = self.equity_curve[-1] if self.equity_curve else self.starting_cash
        daily_ret = (equity_post / prior_equity - 1.0) if prior_equity > 0 else 0.0

        self.cash_curve.append(cash)
        self.equity_curve.append(equity_post)
        self.positions = positions_after
        self.daily_returns.append(daily_ret)
        self.asof_history.append(asof)
        self.trade_log.extend(trades)

        weights = {s: v / equity_post for s, v in positions_after.items()} if equity_post > 0 else {}

        return StepResult(
            asof=asof,
            equity=equity_post,
            cash=cash,
            positions=dict(positions_after),
            weights=weights,
            daily_return=daily_ret,
            trades=tuple(trades),
        )

    def summary(self) -> dict[str, float]:
        if not self.equity_curve:
            return {"start_equity": self.starting_cash, "end_equity": self.starting_cash}
        ec = self.equity_curve
        start, end = self.starting_cash, ec[-1]
        total_ret = end / start - 1.0
        days = len(ec)
        cagr = (end / start) ** (252 / max(days, 1)) - 1.0 if start > 0 else 0.0

        # Max DD
        peak = ec[0]
        max_dd = 0.0
        for v in ec:
            peak = max(peak, v)
            if peak > 0:
                dd = v / peak - 1.0
                max_dd = min(max_dd, dd)

        # Sharpe (rough; daily mean / daily stdev × sqrt(252), 0 rf)
        if len(self.daily_returns) >= 2:
            mean = sum(self.daily_returns) / len(self.daily_returns)
            var = sum((r - mean) ** 2 for r in self.daily_returns) / (len(self.daily_returns) - 1)
            sd = math.sqrt(var) if var > 0 else 0.0
            sharpe = (mean / sd * math.sqrt(252)) if sd > 0 else 0.0
            realized_vol = sd * math.sqrt(252)
        else:
            sharpe = 0.0
            realized_vol = 0.0

        return {
            "start_equity": start,
            "end_equity": end,
            "total_return": total_ret,
            "cagr": cagr,
            "max_drawdown": max_dd,
            "sharpe": sharpe,
            "realized_vol_annualized": realized_vol,
            "n_trading_days": days,
            "n_trades": len(self.trade_log),
        }

    # ── Persistence ─────────────────────────────────────────────────────

    SCHEMA_VERSION: int = 1

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict for state persistence."""
        return {
            "schema_version": self.SCHEMA_VERSION,
            "starting_cash": self.starting_cash,
            "slippage_bps": self.slippage_bps,
            "positions": dict(self.positions),
            "equity_curve": list(self.equity_curve),
            "cash_curve": list(self.cash_curve),
            "daily_returns": list(self.daily_returns),
            "asof_history": [d.isoformat() for d in self.asof_history],
            "trade_log": [
                {
                    "asof": t.asof.isoformat(),
                    "symbol": t.symbol,
                    "side": t.side,
                    "notional": t.notional,
                    "pre_weight": t.pre_weight,
                    "target_weight": t.target_weight,
                }
                for t in self.trade_log
            ],
            "last_close": dict(getattr(self, "_last_close", {})),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "ShadowBook":
        """Deserialize from a previously-saved dict."""
        ver = payload.get("schema_version", 1)
        if ver != cls.SCHEMA_VERSION:
            raise ValueError(
                f"ShadowBook state schema version {ver} != {cls.SCHEMA_VERSION}; "
                f"manual migration required"
            )
        book = cls(
            starting_cash=float(payload["starting_cash"]),
            slippage_bps=float(payload.get("slippage_bps", 5.0)),
        )
        book.positions = {k: float(v) for k, v in payload.get("positions", {}).items()}
        book.equity_curve = [float(x) for x in payload.get("equity_curve", [])]
        book.cash_curve = [float(x) for x in payload.get("cash_curve", [])]
        book.daily_returns = [float(x) for x in payload.get("daily_returns", [])]
        book.asof_history = [date.fromisoformat(s) for s in payload.get("asof_history", [])]
        book.trade_log = [
            TradeRecord(
                asof=date.fromisoformat(t["asof"]),
                symbol=t["symbol"],
                side=t["side"],
                notional=float(t["notional"]),
                pre_weight=float(t["pre_weight"]),
                target_weight=float(t["target_weight"]),
            )
            for t in payload.get("trade_log", [])
        ]
        book._last_close = {
            k: float(v) for k, v in payload.get("last_close", {}).items()
        }
        return book

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), indent=2))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path) -> "ShadowBook":
        return cls.from_dict(json.loads(path.read_text()))
