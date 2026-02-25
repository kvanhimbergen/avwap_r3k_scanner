# New Alpaca Automated Strategy Template

Guide and prompt template for creating new automated trading strategies that execute via the Alpaca paper trading API. Mirrors the architecture of V1 (`raec_401k.py`) and V2 (`raec_401k_v2.py`).

---

## Architecture Overview

```
                  ops/post_scan_pipeline.py
                          |
          python -m strategies.{your_module} --asof YYYY-MM-DD
                          |
               strategies/{your_module}.py
                    run_strategy()
                          |
        +--------+--------+--------+--------+
        |        |        |        |        |
    load      compute    build    build    execute
    prices    signals    targets  intents  via adapter
        |        |        |        |        |
  data/prices  VTI anchor  regime   delta    AlpacaRebalanceAdapter
  .py          + features  alloc    pct →      .send_summary_ticket()
                           map     orders        |
                                          +------+------+
                                          |      |      |
                                        sells  buys  ledger
                                        first  second  write
```

### Key Contracts

| Concept | Description |
|---------|-------------|
| **BOOK_ID** | `ALPACA_PAPER` — routes to Alpaca paper trading client |
| **STRATEGY_ID** | Unique string, e.g. `"MY_STRATEGY_V1"` — used in state path, ledger path, intent IDs |
| **State** | JSON at `state/strategies/ALPACA_PAPER/{STRATEGY_ID}.json` |
| **Ledger** | JSONL at `ledger/RAEC_REBALANCE/{STRATEGY_ID}/{date}.jsonl` |
| **Order ledger** | JSONL at `ledger/ALPACA_PAPER/{date}.jsonl` (shared across all Alpaca strategies) |
| **Adapter** | `AlpacaRebalanceAdapter` — converts pct-delta intents to Alpaca market orders |
| **PriceProvider** | Protocol returning `list[tuple[date, float]]` per symbol (Yahoo Finance in prod, fixtures in tests) |

---

## Files to Create

### 1. Strategy module: `strategies/{your_module}.py`

This is the core strategy file. Must export:
- `BOOK_ID`, `STRATEGY_ID`, `DEFAULT_UNIVERSE` (module-level constants)
- `run_strategy(**kwargs) -> RunResult` (main entry point)
- `main(argv) -> int` (CLI entry point)

### 2. Test file: `tests/test_{your_module}.py`

Mirror the test patterns in `tests/test_raec_401k.py` and `tests/test_raec_401k_v2.py`.

### 3. Pipeline step in `ops/post_scan_pipeline.py`

Add a new step to the pipeline's `STEPS` list.

---

## Files to Modify

| File | Change |
|------|--------|
| `ops/post_scan_pipeline.py` | Add pipeline step |

No registry needed for standalone Alpaca strategies (registry is only for V3/V4/V5 `BaseRAECStrategy` subclasses).

---

## Strategy Module Template

Reference implementations: `strategies/raec_401k.py` (V1, 350 lines) and `strategies/raec_401k_v2.py` (V2, 870 lines).

### Required Structure

```python
"""One-line description of the strategy."""

from __future__ import annotations

import argparse, hashlib, json, math, os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import stdev
from typing import Any, Iterable

from data.prices import PriceProvider, get_default_price_provider
from execution_v2 import book_ids, book_router
from execution_v2.alpaca_rebalance_adapter import AlpacaRebalanceAdapter
from utils.atomic_write import atomic_write_text

BOOK_ID = book_ids.ALPACA_PAPER
STRATEGY_ID = "YOUR_STRATEGY_ID"          # must be unique across all strategies

# --- Universe ---
RISK_UNIVERSE = (...)                       # ETFs to hold in risk-on
DEFENSIVE_UNIVERSE = (...)                  # ETFs to hold in risk-off
DEFAULT_UNIVERSE = tuple(dict.fromkeys([*RISK_UNIVERSE, *DEFENSIVE_UNIVERSE]))
FALLBACK_CASH_SYMBOL = "BIL"

# --- Trading limits ---
MIN_TRADE_PCT = 0.5                         # ignore deltas smaller than this
MAX_WEEKLY_TURNOVER_PCT = 15.0              # cap total buys per cycle
DRIFT_THRESHOLD_PCT = 2.5                   # force rebalance above this drift
TARGET_PORTFOLIO_VOL = 0.12                 # annualized vol target (optional)
MAX_SINGLE_ETF_WEIGHT = 0.45               # max weight per ETF (optional)
```

### Required Dataclasses

```python
@dataclass(frozen=True)
class RegimeSignal:
    """Anchor signal computed from VTI (or your anchor symbol)."""
    regime: str           # "RISK_ON" | "TRANSITION" | "RISK_OFF"
    close: float
    sma50: float
    sma200: float
    vol_20d: float
    vol_252d: float
    # V2 additions (optional):
    drawdown_63d: float
    trend_up: bool
    vol_high: bool
    crash_mode: bool

@dataclass(frozen=True)
class RunResult:
    """Returned by run_strategy()."""
    asof_date: str
    regime: str
    targets: dict[str, float]              # symbol -> target pct (sums to 100)
    intents: list[dict]                    # order intents (sells first, then buys)
    should_rebalance: bool
    posting_enabled: bool
    posted: bool
    notice: str | None
```

### Required Functions

#### State persistence
```python
def _state_path(repo_root: Path) -> Path:
    return repo_root / "state" / "strategies" / BOOK_ID / f"{STRATEGY_ID}.json"

def _load_state(path: Path) -> dict: ...
def _save_state(path: Path, state: dict) -> None: ...
```

#### Ledger writing
```python
def _write_raec_ledger(result: RunResult, *, repo_root, targets, current_allocations,
                        signals, momentum_scores, build_git_sha=None) -> None:
    """Append RAEC_REBALANCE_EVENT to ledger/RAEC_REBALANCE/{STRATEGY_ID}/{date}.jsonl"""
```

The ledger record schema is:
```json
{
  "record_type": "RAEC_REBALANCE_EVENT",
  "ts_utc": "ISO8601",
  "ny_date": "YYYY-MM-DD",
  "book_id": "ALPACA_PAPER",
  "strategy_id": "YOUR_STRATEGY_ID",
  "regime": "RISK_ON",
  "should_rebalance": true,
  "rebalance_trigger": "monthly",
  "targets": {"VTI": 40.0, "BIL": 60.0},
  "current_allocations": {"VTI": 35.0, "BIL": 65.0},
  "intent_count": 2,
  "intents": [...],
  "signals": {...},
  "momentum_scores": [...],
  "portfolio_vol_target": 0.12,
  "portfolio_vol_realized": null,
  "posted": false,
  "notice": null,
  "build_git_sha": null
}
```

#### Signal computation
```python
def _compute_anchor_signal(series: list[tuple[date, float]]) -> RegimeSignal:
    """VTI-based regime classification. Requires 253+ daily closes."""
```

V1 regime rules (simple):
- **RISK_ON**: `close > SMA200` and `SMA50 > SMA200` and `vol_20d <= vol_252d * 1.25`
- **TRANSITION**: `close > SMA200` and (vol_high or not trend_up)
- **RISK_OFF**: everything else

V2 regime rules (adds drawdown):
- **RISK_ON**: trend_up and `drawdown_63d > -4%` and not vol_high
- **TRANSITION**: `close > SMA200` and `drawdown_63d > -8%`
- **RISK_OFF**: everything else

#### Target allocation
```python
def _targets_for_regime(*, signal, feature_map, cash_symbol) -> dict[str, float]:
    """Return {symbol: pct} summing to 100.0 based on regime."""
```

V1: Static allocation maps per regime.
V2: Dynamic momentum ranking + inverse-vol weighting + vol-scaling + weight capping.

#### Rebalance gating
```python
def _should_rebalance(*, asof, state, regime, targets, current_allocs) -> bool:
    """Gate: first-of-month OR regime change OR drift > threshold."""
```

#### Intent building
```python
def _build_intents(*, asof_date, targets, current, min_trade_pct, max_weekly_turnover) -> list[dict]:
    """Compute pct deltas, apply turnover cap, return sell-first intent list."""
```

Each intent dict must contain:
```python
{
    "symbol": str,
    "side": "BUY" | "SELL",
    "delta_pct": float,
    "target_pct": float,
    "current_pct": float,
    "strategy_id": STRATEGY_ID,
    "intent_id": str,       # deterministic SHA256
    "ref_price": float,     # last close — needed by adapter for share calc
}
```

#### Main entry point
```python
def run_strategy(
    *,
    asof_date: str,
    repo_root: Path,
    price_provider: PriceProvider | None = None,
    dry_run: bool = False,
    allow_state_write: bool = False,
    post_enabled: bool | None = None,
    adapter_override: object | None = None,   # for test injection
) -> RunResult:
```

The `run_strategy` flow is:
1. Load price provider (or accept injected one)
2. Compute anchor signal from VTI series
3. (V2 only) Load per-symbol features and rank by momentum
4. Compute target allocation for current regime
5. Build adapter (lazy — only when `not dry_run`)
6. Load current allocations: try Alpaca live first, fall back to state, fall back to targets
7. Check rebalance gate
8. Build intents with turnover cap
9. Attach `ref_price` to each intent (last close)
10. Execute via `adapter.send_summary_ticket()` or print ticket (dry_run)
11. Save state + write ledger

#### CLI
```python
def parse_args(argv=None) -> argparse.Namespace: ...

def main(argv=None) -> int:
    # parse args, resolve repo_root, run_strategy, print structured summary
    # Summary line format (grep target):
    # ALPACA_PAPER: tickets_sent=N asof=YYYY-MM-DD should_rebalance=0|1 ...
```

---

## Adapter Interface

`AlpacaRebalanceAdapter` (`execution_v2/alpaca_rebalance_adapter.py`) provides:

```python
class AlpacaRebalanceAdapter:
    def __init__(self, trading_client: TradingClient): ...

    def get_account_equity(self) -> float: ...

    def get_current_allocations(self, cash_symbol: str) -> dict[str, float]:
        """Portfolio as pct allocations. Maps USD cash to cash_symbol."""

    def send_summary_ticket(self, intents, *, message, ny_date, repo_root,
                            post_enabled=None) -> RebalanceOrderResult:
        """Checks ALPACA_REBALANCE_ENABLED, then executes sell-first rebalance.
        Converts pct deltas to share quantities using equity * delta / ref_price.
        Skips cash_symbol and NOTICE/INFO intents."""

    def execute_rebalance(self, intents, *, ny_date, repo_root,
                          strategy_id="", cash_symbol="BIL") -> RebalanceOrderResult:
        """Low-level: submit MarketOrderRequest for each intent, log to ledger."""
```

`RebalanceOrderResult`:
```python
@dataclass(frozen=True)
class RebalanceOrderResult:
    ny_date: str
    sent: int        # orders successfully submitted
    skipped: int     # intents skipped (cash, NOTICE, zero-share, no ref_price)
    orders: list[dict]
    errors: list[str]
```

---

## Test Patterns

### Fixtures

```python
from datetime import date, timedelta
from data.prices import FixturePriceProvider

def _linear_series(start_price, end_price, days=300, start_date=None):
    """Create trending price data with small wiggle for realism."""
    if start_date is None:
        start_date = date.today() - timedelta(days=days)
    step = (end_price - start_price) / days
    series = []
    for i in range(days):
        d = start_date + timedelta(days=i)
        price = start_price + step * i + (0.01 * (i % 3))  # tiny wiggle
        series.append((d, round(price, 2)))
    return series

def _make_provider(**overrides):
    """Build a FixturePriceProvider with sensible defaults."""
    data = {"VTI": _linear_series(250, 340), "BIL": _linear_series(91, 91.5)}
    data.update(overrides)
    return FixturePriceProvider(data)
```

### Standard Test Cases

1. **Regime classification** — verify RISK_ON / TRANSITION / RISK_OFF from price shapes
2. **Target allocation** — verify targets sum to 100%, correct symbols per regime
3. **Rebalance gating** — first-of-month triggers, regime change triggers, drift triggers
4. **Turnover cap** — verify buys are scaled down when exceeding max_weekly_turnover
5. **Intent ordering** — sells before buys
6. **Dry-run isolation** — no state/ledger writes when `dry_run=True, allow_state_write=False`
7. **State persistence** — verify state JSON is written with correct fields
8. **Ledger format** — verify JSONL record has all required fields
9. **Adapter integration** — mock `AlpacaRebalanceAdapter`, verify `send_summary_ticket` called correctly
10. **Edge cases** — empty universe, no positive momentum, zero equity, missing price data

### Test Skeleton

```python
import json
from pathlib import Path
from strategies.your_module import run_strategy, _compute_anchor_signal, STRATEGY_ID

class TestRegime:
    def test_risk_on(self, tmp_path):
        provider = _make_provider(VTI=_linear_series(250, 340))
        result = run_strategy(
            asof_date="2026-01-15", repo_root=tmp_path,
            price_provider=provider, dry_run=True,
        )
        assert result.regime == "RISK_ON"

    def test_risk_off(self, tmp_path):
        provider = _make_provider(VTI=_linear_series(340, 250))
        result = run_strategy(
            asof_date="2026-01-15", repo_root=tmp_path,
            price_provider=provider, dry_run=True,
        )
        assert result.regime == "RISK_OFF"

class TestRebalanceGating:
    def test_first_of_month_triggers(self, tmp_path):
        provider = _make_provider()
        result = run_strategy(
            asof_date="2026-02-03", repo_root=tmp_path,
            price_provider=provider, dry_run=True, allow_state_write=True,
        )
        assert result.should_rebalance is True

    def test_no_drift_skips(self, tmp_path):
        provider = _make_provider()
        # First run to seed state
        run_strategy(
            asof_date="2026-02-03", repo_root=tmp_path,
            price_provider=provider, dry_run=True, allow_state_write=True,
        )
        # Same month, same regime, no drift
        result = run_strategy(
            asof_date="2026-02-04", repo_root=tmp_path,
            price_provider=provider, dry_run=True, allow_state_write=True,
        )
        assert result.should_rebalance is False

class TestIntents:
    def test_sells_before_buys(self, tmp_path):
        provider = _make_provider()
        result = run_strategy(
            asof_date="2026-01-15", repo_root=tmp_path,
            price_provider=provider, dry_run=True, allow_state_write=True,
        )
        if len(result.intents) > 1:
            sell_indices = [i for i, x in enumerate(result.intents) if x["side"] == "SELL"]
            buy_indices = [i for i, x in enumerate(result.intents) if x["side"] == "BUY"]
            if sell_indices and buy_indices:
                assert max(sell_indices) < min(buy_indices)

class TestLedger:
    def test_ledger_written(self, tmp_path):
        provider = _make_provider()
        run_strategy(
            asof_date="2026-01-15", repo_root=tmp_path,
            price_provider=provider, dry_run=False, allow_state_write=True,
            post_enabled=False,
        )
        ledger_dir = tmp_path / "ledger" / "RAEC_REBALANCE" / STRATEGY_ID
        files = list(ledger_dir.glob("*.jsonl"))
        assert len(files) == 1
        records = [json.loads(line) for line in files[0].read_text().splitlines()]
        assert records[0]["record_type"] == "RAEC_REBALANCE_EVENT"
        assert records[0]["strategy_id"] == STRATEGY_ID
```

---

## Pipeline Wiring

In `ops/post_scan_pipeline.py`, add a step to the `STEPS` list:

```python
Step(
    name="your_strategy_name",
    cmd=[
        sys.executable, "-m", "strategies.your_module",
        "--asof", "{asof}",
    ],
    dry_run_flag="--dry-run",      # appended when pipeline runs in dry-run mode
),
```

Steps run sequentially. Place your step after regime/throttle computation (steps 1-2) and after any strategies it depends on.

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ALPACA_REBALANCE_ENABLED` | `"1"` | Kill switch for order submission (checked by adapter) |
| `DRY_RUN` | `"0"` | Global dry-run override |
| `APCA_API_KEY_ID` | (required) | Alpaca paper trading API key |
| `APCA_API_SECRET_KEY` | (required) | Alpaca paper trading API secret |

---

## Running Locally

```bash
# Dry run (no orders, no state writes, prints ticket to stdout)
python -m strategies.your_module --asof 2026-02-18 --dry-run

# Dry run with state writes (seeds state for next run)
python -m strategies.your_module --asof 2026-02-18 --dry-run --allow-state-write

# Live paper trading (submits orders to Alpaca paper account)
python -m strategies.your_module --asof 2026-02-18

# Run tests
./venv/bin/pytest tests/test_your_module.py -x -v
```

---

## Prompt Template

Copy and fill in the sections below, then provide it as a prompt to create the implementation.

```
Create a new automated Alpaca paper trading strategy with the following specifications.
Mirror the architecture of strategies/raec_401k_v2.py (V2 dynamic factor rotation).

## Identity
- Module: strategies/{module_name}.py
- STRATEGY_ID: "{STRATEGY_ID}"
- BOOK_ID: ALPACA_PAPER

## Universe
- Risk-on ETFs: {comma-separated list, e.g. "QQQ, SPY, IWM, TQQQ, SOXL"}
- Defensive ETFs: {comma-separated list, e.g. "TLT, GLD, USMV, BIL"}
- Cash proxy: BIL

## Signal / Regime Logic
{Describe how the strategy determines the market regime. Options:}
- Anchor symbol: {VTI, SPY, QQQ, or custom}
- Regime classification rules:
  - RISK_ON: {conditions}
  - TRANSITION: {conditions}
  - RISK_OFF: {conditions}
- Additional signals: {e.g. drawdown circuit breaker at -X%, dual-anchor, sector breadth}

## Allocation Logic
- RISK_ON:
  - Top N risk ETFs: {N}
  - Weighting method: {inverse-vol, equal-weight, momentum-weighted, custom}
  - Max single ETF weight: {pct}
  - Max risk budget: {pct of portfolio}
  - Min cash floor: {pct}
- TRANSITION:
  - Top N risk ETFs: {N}, budget: {pct}
  - Top N defensive ETFs: {N}, budget: {pct}
  - Min cash floor: {pct}
- RISK_OFF:
  - Top N defensive ETFs: {N}, budget: {pct}
  - Min cash floor: {pct}

## Momentum / Ranking
- Lookback windows: {e.g. 6-month and 12-month}
- Score formula: {e.g. "(mom_6m * 0.65 + mom_12m * 0.35) / vol_20d"}
- Require positive momentum in risk-on: {yes/no}
- Vol scaling: {target portfolio vol, e.g. 0.12 annualized}

## Trading Limits
- Min trade size: {pct, e.g. 0.5%}
- Max weekly turnover: {pct, e.g. 15%}
- Drift threshold for forced rebalance: {pct, e.g. 2.5%}
- Rebalance trigger: {monthly + regime change + drift, or custom}

## Crash / Risk-Off Overrides
- Crash mode trigger: {e.g. drawdown_63d <= -8%}
- Crash mode effect: {e.g. scale risk budget by 0.70}

## Additional Requirements
{Any custom behavior, e.g.:}
- {Sector rotation constraints}
- {Correlation-based diversification}
- {Custom signal overlays}
- {Leverage limits}

## Files to Create
1. strategies/{module_name}.py — Full strategy implementation
2. tests/test_{module_name}.py — Comprehensive test suite

## Files to Modify
1. ops/post_scan_pipeline.py — Add pipeline step after step {N}

## Implementation Notes
- Use AlpacaRebalanceAdapter for order execution (lazy init, only when not dry_run)
- Adapter is obtained via: book_router.select_trading_client(BOOK_ID)
- State persisted to state/strategies/ALPACA_PAPER/{STRATEGY_ID}.json
- Ledger appended to ledger/RAEC_REBALANCE/{STRATEGY_ID}/{date}.jsonl
- Intent IDs are deterministic SHA256 hashes of (book_id, strategy_id, date, symbol, side, target_pct)
- Intents must include ref_price (last close) for adapter share calculation
- Sells are always ordered before buys in the intent list
- Support adapter_override parameter for test injection
- Print structured summary line: "ALPACA_PAPER: tickets_sent=N asof=..."
- Use atomic_write_text for state file writes
- Use FixturePriceProvider + _linear_series() for test fixtures
- Run tests with: ./venv/bin/pytest tests/test_{module_name}.py -x -v
```
