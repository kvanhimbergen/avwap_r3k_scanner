"""DryRunAdapter — Slack output for the v6 dry-run coordinator.

Safety contract:
- The adapter REFUSES to operate on the live SCHWAB_401K_MANUAL book.
- The adapter REFUSES to emit a "go live" message even if asked.
- Live trade execution from v6 will go through a *different* adapter
  built in Phase F (cutover).

This is intentional belt-and-suspenders so a single misconfigured flag
can never accidentally cause v6 to post live trade instructions next to
the running V3/V4/V5 coordinator.

Output format: `[V6 DRY]` prefix on every Slack message, component
"RAEC_V6_DRY" so logs and dashboards can distinguish.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping

from alerts.slack import slack_alert_sync


# Hard-coded — this adapter only operates on the v6 dry-run book.
DRY_RUN_BOOK_ID = "RAEC_V6_DRY_RUN"
LIVE_BOOK_ID = "SCHWAB_401K_MANUAL"
COMPONENT = "RAEC_V6_DRY"


class V6DryRunSafetyError(RuntimeError):
    """Raised if the adapter is asked to do anything live-trade-shaped."""


@dataclass(frozen=True)
class V6Intent:
    """One line of a v6 ticket: target weight change for one symbol."""

    symbol: str
    side: str  # "BUY" or "SELL"
    delta_pct: float  # signed pct-of-book delta
    target_pct: float
    current_pct: float
    dollar_delta: float


def _format_ticket(
    *,
    asof: date,
    equity: float,
    cash: float,
    rebalance: bool,
    intents: list[V6Intent],
    regime_label: str,
    target_vol: float,
    forecast_vol: float,
    exposure_scale: float,
    strategy_shares: Mapping[str, float],
    notice: str | None,
) -> str:
    """Human-readable advisory ticket for Slack."""
    lines: list[str] = [
        f"RAEC V6 (Dry-Run) — {asof.isoformat()}",
        f"Book: {DRY_RUN_BOOK_ID}  Shadow equity: ${equity:,.0f}  Cash: ${cash:,.0f}",
        f"Regime: {regime_label}  Target vol: {target_vol:.1%}  Forecast vol: {forecast_vol:.1%}",
        f"Exposure scale: {exposure_scale:.2f}×",
        "",
        "Strategy shares:",
    ]
    for sid, share in sorted(strategy_shares.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {sid:30s} {share:6.1%}")
    lines.append("")
    if not rebalance:
        lines.append(f"NO REBALANCE TODAY — {notice or 'within tolerance'}")
    else:
        lines.append("Intents (advisory only, no orders submitted):")
        for ix in sorted(intents, key=lambda x: -abs(x.delta_pct)):
            lines.append(
                f"  {ix.side:4s} {ix.symbol:6s} Δ {ix.delta_pct:+.1%} | "
                f"target {ix.target_pct:.1%} | current {ix.current_pct:.1%} | "
                f"${ix.dollar_delta:+,.0f}"
            )
    return "\n".join(lines)


class DryRunAdapter:
    """Posts a v6 dry-run advisory ticket to Slack.

    Hard refusal of any live-mode call.
    """

    def __init__(self, *, book_id: str = DRY_RUN_BOOK_ID) -> None:
        if book_id != DRY_RUN_BOOK_ID:
            raise V6DryRunSafetyError(
                f"DryRunAdapter constructed with book_id={book_id!r}; "
                f"this adapter only operates on {DRY_RUN_BOOK_ID}. "
                f"Live trade adapter for v6 will be built separately in Phase F."
            )
        self._book_id = book_id

    @property
    def book_id(self) -> str:
        return self._book_id

    def post_advisory(
        self,
        *,
        asof: date,
        equity: float,
        cash: float,
        rebalance: bool,
        intents: list[V6Intent],
        regime_label: str,
        target_vol: float,
        forecast_vol: float,
        exposure_scale: float,
        strategy_shares: Mapping[str, float],
        notice: str | None = None,
    ) -> str:
        """Emit a `[V6 DRY]` advisory to Slack. Returns the message text
        (also handy for tests + ledger archiving).
        """
        text = _format_ticket(
            asof=asof,
            equity=equity,
            cash=cash,
            rebalance=rebalance,
            intents=intents,
            regime_label=regime_label,
            target_vol=target_vol,
            forecast_vol=forecast_vol,
            exposure_scale=exposure_scale,
            strategy_shares=strategy_shares,
            notice=notice,
        )
        title = f"[V6 DRY] {asof.isoformat()}  (advisory only)"
        slack_alert_sync(
            level="INFO" if not rebalance else "TRADE",
            title=title,
            message=text,
            component=COMPONENT,
        )
        return text

    def post_live(self, **_kwargs: object) -> None:
        """Hard refusal: this adapter NEVER posts live trade instructions.

        Phase F will introduce a separate LiveTradeAdapter once cutover
        criteria are met. Until then, any call to post_live is a
        configuration bug.
        """
        raise V6DryRunSafetyError(
            "DryRunAdapter cannot post live trade instructions. "
            f"This adapter only emits [V6 DRY] advisories against "
            f"{DRY_RUN_BOOK_ID}. To go live, swap in the Phase F "
            f"LiveTradeAdapter and update the coordinator wiring."
        )

    def post_error(
        self, *, asof: date, error: str, component_detail: str | None = None
    ) -> None:
        """Operational ERROR message — coordinator failures, etc."""
        title = f"[V6 DRY] ERROR  {asof.isoformat()}"
        message = error if not component_detail else f"{component_detail}\n{error}"
        slack_alert_sync(level="ERROR", title=title, message=message, component=COMPONENT)
