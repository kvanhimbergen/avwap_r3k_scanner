"""RAEC v6 — multi-strategy ensemble with conviction-weighted risk-parity allocator.

Greenfield redesign of the 401(k) trading system. Runs in parallel dry-run
alongside the live V3/V4/V5 coordinator until cutover criteria are met.

Layers:
- Signal: SignalState built from regime + cross-asset signals (see signals/)
- Strategy: each strategy is a pure function (state, prices, asof) -> StrategyOutput
- Allocator: conviction-weighted risk parity + per-symbol cap + correlation derate
- Overlay: vol forecast (max of trailing realized / ewma / vix-implied) + DD breaker

Plan: /Users/kevinvanhimbergen/.claude/plans/fluffy-enchanting-fog.md
"""
