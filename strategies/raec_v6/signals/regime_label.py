"""Lightweight historical regime classifier for backtest use.

Mirrors the labeling logic of analytics.regime_e1_classifier.classify_regime
but computes features directly from SPY closes rather than the parquet
history pipeline. Output labels match exactly: RISK_ON, NEUTRAL, RISK_OFF,
STRESSED.

In live operation, the coordinator should prefer the real E1 ledger
(analytics/regime_e1_runner.py) — this module is for backtest
reconstruction where we don't have a full history parquet.

Thresholds mirror analytics/regime_e1_classifier.py (volatility 0.20/0.30,
drawdown -0.10/-0.20, trend ±0.02). Breadth signal is not available without
the full universe history; this implementation passes breadth=0.50 (neutral)
so the four-of-four RISK_ON rule degrades gracefully.
"""

from __future__ import annotations

import math
from datetime import date


VOL_HIGH = 0.30
VOL_MODERATE = 0.20
DRAWDOWN_STRESSED = -0.20
DRAWDOWN_RISK_OFF = -0.10
TREND_DOWN = -0.02
TREND_UP = 0.02
BREADTH_STRONG = 0.55
BREADTH_WEAK = 0.45
NEUTRAL_BREADTH = 0.50


def _annualized_vol(closes: list[float], window: int = 20) -> float:
    if len(closes) < window + 1:
        return 0.0
    rs: list[float] = []
    for i in range(len(closes) - window, len(closes)):
        if i > 0 and closes[i - 1] > 0:
            rs.append(closes[i] / closes[i - 1] - 1.0)
    if len(rs) < 5:
        return 0.0
    mean = sum(rs) / len(rs)
    var = sum((r - mean) ** 2 for r in rs) / (len(rs) - 1)
    if var <= 0:
        return 0.0
    return math.sqrt(var) * math.sqrt(252)


def _drawdown(closes: list[float], window: int = 252) -> float:
    if not closes:
        return 0.0
    win = closes[-window:]
    peak = max(win)
    if peak <= 0:
        return 0.0
    return win[-1] / peak - 1.0


def _trend(closes: list[float], sma_short_n: int = 50, sma_long_n: int = 200) -> float:
    """SMA50 / SMA200 - 1. Positive = golden-cross territory."""
    if len(closes) < sma_long_n:
        return 0.0
    sma_short = sum(closes[-sma_short_n:]) / sma_short_n
    sma_long = sum(closes[-sma_long_n:]) / sma_long_n
    if sma_long <= 0:
        return 0.0
    return sma_short / sma_long - 1.0


def classify_from_spy_closes(closes: list[float]) -> tuple[str, float]:
    """Return (regime_label, confidence) using the E1 classifier thresholds.

    Requires ≥200 closes (for SMA200). Returns ("UNKNOWN", 0.0) below that.
    """
    if len(closes) < 200:
        return ("UNKNOWN", 0.0)

    vol = _annualized_vol(closes)
    dd = _drawdown(closes)
    tr = _trend(closes)
    breadth = NEUTRAL_BREADTH

    stressed_reasons: list[str] = []
    if vol >= VOL_HIGH:
        stressed_reasons.append("vol_high")
    if dd <= DRAWDOWN_STRESSED:
        stressed_reasons.append("drawdown_deep")
    if tr <= TREND_DOWN:
        stressed_reasons.append("trend_down")

    if (vol >= VOL_HIGH and (dd <= DRAWDOWN_STRESSED or tr <= TREND_DOWN)) or dd <= DRAWDOWN_STRESSED:
        confidence = min(1.0, 0.7 + 0.1 * len(stressed_reasons))
        return ("STRESSED", round(confidence, 3))

    risk_off_reasons: list[str] = []
    if vol >= VOL_MODERATE:
        risk_off_reasons.append("vol_elevated")
    if dd <= DRAWDOWN_RISK_OFF:
        risk_off_reasons.append("drawdown_moderate")
    if tr < 0:
        risk_off_reasons.append("trend_negative")
    if breadth <= BREADTH_WEAK:
        risk_off_reasons.append("breadth_weak")

    if risk_off_reasons:
        confidence = min(0.9, 0.5 + 0.1 * len(risk_off_reasons))
        return ("RISK_OFF", round(confidence, 3))

    if (
        vol <= VOL_MODERATE
        and dd > DRAWDOWN_RISK_OFF
        and tr >= TREND_UP
        and breadth >= BREADTH_STRONG
    ):
        confidence = 0.7  # Can never hit 4-reason confidence with breadth=neutral
        return ("RISK_ON", confidence)

    return ("NEUTRAL", 0.4)
