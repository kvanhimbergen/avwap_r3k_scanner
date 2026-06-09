"""LiveTradeAdapter — manual ticket emitter for v6 in live mode.

Posts an executable Slack ticket matching V3-V5 conventions:
- Same Reply protocol (EXECUTED / PARTIAL / SKIPPED / ERROR with intent_id)
- Same `Order intents (sells first)` ordering so the user's habitual
  parsing still works
- Component "RAEC_V6" (no [V6 DRY] prefix) so it appears alongside the
  existing live alerts on the main channel

Intent IDs are SHA256-based and embedded in the ledger so the user's
reply can be matched back to the exact instruction.

Safety: this adapter is for the LIVE Schwab book only. The dry-run
DryRunAdapter remains the separate code path; live and dry never share
a class instance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Mapping

from alerts.slack import slack_alert_sync
from strategies.raec_v6.dry_run_adapter import V6DryRunSafetyError


LIVE_BOOK_ID = "SCHWAB_401K_MANUAL"
COMPONENT = "RAEC_V6"
TICKET_TITLE = "RAEC v6 Rebalance Ticket"


@dataclass(frozen=True)
class LiveIntent:
    """One executable line of the v6 ticket.

    intent_id is hashed from (asof, symbol, side, target_pct, current_pct)
    so the user can reply with that ID and we know exactly which
    instruction was executed.
    """

    intent_id: str
    symbol: str
    side: str
    delta_pct: float
    target_pct: float
    current_pct: float
    dollar_delta: float
    shares_delta: int | None  # None when no price available


def make_intent_id(
    *,
    asof: date,
    symbol: str,
    side: str,
    target_pct: float,
    current_pct: float,
) -> str:
    """Deterministic intent ID. Same inputs → same ID, so a re-run of the
    same date produces matchable ledger entries."""
    raw = json.dumps(
        {
            "asof": asof.isoformat(),
            "symbol": symbol,
            "side": side,
            "target_pct": round(target_pct, 4),
            "current_pct": round(current_pct, 4),
        },
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _format_intent_row(ix: LiveIntent) -> str:
    """One compact line per intent: id_prefix · SYM ±%pct $±amount (±Nsh)."""
    sh = f"  ({ix.shares_delta:+d} sh)" if ix.shares_delta is not None else ""
    return (
        f"  {ix.intent_id[:8]}  {ix.symbol:<5s}  "
        f"{ix.delta_pct * 100:+5.1f}%  ${ix.dollar_delta:+,.0f}{sh}"
    )


def _format_ticket(
    *,
    asof: date,
    equity: float,
    cash_pct: float,
    rebalance: bool,
    regime_label: str,
    target_vol: float,
    forecast_vol: float,
    exposure_scale: float,
    strategy_shares: Mapping[str, float],
    intents: list[LiveIntent],
    notice: str | None,
) -> str:
    """Compact ticket format.

    See feedback memory `feedback-slack-tickets-tight`: targets ≤12 lines
    typical, ≤25 day-1. Drops the per-strategy block (lives in the ledger
    + dashboard) and the multi-line checklist (reply protocol line is
    enough).
    """
    lines: list[str] = [
        f"RAEC v6  •  {asof.isoformat()}  •  {regime_label}",
        f"${equity:,.0f}  •  Cash {cash_pct:.1%}  •  "
        f"Vol target {target_vol:.1%} (forecast {forecast_vol:.1%}, scale {exposure_scale:.2f}×)",
    ]
    if notice:
        lines.append(f"NOTICE: {notice}")
    if not intents:
        lines.append("")
        lines.append("No trades — allocations at target.")
        lines.append("")
        lines.append("Reply: EXECUTED / PARTIAL / SKIPPED / ERROR + intent_id")
        return "\n".join(lines)

    sells = sorted(
        (i for i in intents if i.side == "SELL"),
        key=lambda i: -abs(i.delta_pct),
    )
    buys = sorted(
        (i for i in intents if i.side == "BUY"),
        key=lambda i: -abs(i.delta_pct),
    )
    if sells:
        lines.append("")
        lines.append("SELLS:")
        for ix in sells:
            lines.append(_format_intent_row(ix))
    if buys:
        lines.append("")
        lines.append("BUYS:")
        for ix in buys:
            lines.append(_format_intent_row(ix))
    lines.append("")
    lines.append("Reply: EXECUTED / PARTIAL / SKIPPED / ERROR + intent_id")
    return "\n".join(lines)


class LiveTradeAdapter:
    """Posts the executable v6 ticket to the live Slack channel.

    Bound to BOOK_ID=SCHWAB_401K_MANUAL. Reject any attempt to construct
    against the dry-run book — the v6 dry-run uses DryRunAdapter, not
    this class.
    """

    def __init__(self, *, book_id: str = LIVE_BOOK_ID) -> None:
        if book_id != LIVE_BOOK_ID:
            raise V6DryRunSafetyError(
                f"LiveTradeAdapter must operate on {LIVE_BOOK_ID}; got {book_id!r}. "
                f"Use DryRunAdapter for the dry-run book."
            )
        self._book_id = book_id

    @property
    def book_id(self) -> str:
        return self._book_id

    def post_ticket(
        self,
        *,
        asof: date,
        equity: float,
        cash_pct: float,
        rebalance: bool,
        regime_label: str,
        target_vol: float,
        forecast_vol: float,
        exposure_scale: float,
        strategy_shares: Mapping[str, float],
        intents: list[LiveIntent],
        notice: str | None = None,
    ) -> str:
        """Emit the live executable ticket. Returns the message text."""
        text = _format_ticket(
            asof=asof,
            equity=equity,
            cash_pct=cash_pct,
            rebalance=rebalance,
            regime_label=regime_label,
            target_vol=target_vol,
            forecast_vol=forecast_vol,
            exposure_scale=exposure_scale,
            strategy_shares=strategy_shares,
            intents=intents,
            notice=notice,
        )
        # Title: empty so the slack_alert prefix line carries the date.
        # Level TRADE on rebalance days; INFO on no-trade days.
        slack_alert_sync(
            level="TRADE" if rebalance else "INFO",
            title=f"v6 Rebalance {asof.isoformat()}",
            message=text,
            component=COMPONENT,
        )
        return text

    def post_error(self, *, asof: date, error: str) -> None:
        slack_alert_sync(
            level="ERROR",
            title=f"v6 ERROR {asof.isoformat()}",
            message=error,
            component=COMPONENT,
        )
