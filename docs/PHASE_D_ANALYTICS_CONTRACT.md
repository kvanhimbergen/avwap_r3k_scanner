# Phase D Analytics Contract

## Scope (Read-only)

The analytics layer is **read-only**. It does not submit orders, cancel orders, or invoke any execution code. It only ingests existing ledger files and emits a canonical `Fill` representation for downstream phases.

## Canonical Fill Schema

| Field | Type | Description |
| --- | --- | --- |
| `fill_id` | `str` | Deterministic SHA256 hash over stable fields. |
| `venue` | `str` | `DRY_RUN`, `LIVE`, or `BROKER` (unused in D0). |
| `order_id` | `str` | Ledger order id or deterministic synthetic id. |
| `symbol` | `str` | Uppercased symbol. |
| `side` | `str` | `buy`, `sell`, or `unknown`. |
| `qty` | `float` | Quantity (or notional when that is all that exists). |
| `price` | `float \| None` | Fill price when available. |
| `fees` | `float` | Fees, default `0.0`. |
| `ts_utc` | `str` | ISO 8601 timestamp with timezone (UTC). |
| `ts_ny` | `str` | ISO 8601 timestamp in America/New_York. |
| `date_ny` | `str` | `YYYY-MM-DD` derived in America/New_York. |
| `source_path` | `str` | Ledger file path. |
| `raw_json` | `str \| None` | Compact JSON entry (if serializable). |

## Trade Reconstruction (Phase D1)

Phase D1 reconstructs executed trades from canonical fills using deterministic matching rules. It produces two additional schemas: `Lot` (open positions) and `Trade` (matched open/close segments).

### Lot Schema

| Field | Type | Description |
| --- | --- | --- |
| `lot_id` | `str` | Deterministic SHA256 hash over stable fields. |
| `symbol` | `str` | Uppercased symbol. |
| `side` | `str` | `long` or `short` (short lots are currently unsupported). |
| `open_fill_id` | `str` | Opening fill id. |
| `open_ts_utc` | `str` | Opening timestamp (UTC). |
| `open_date_ny` | `str` | Opening date (NY). |
| `open_qty` | `float` | Original opening quantity. |
| `open_price` | `float \| None` | Opening fill price. |
| `remaining_qty` | `float` | Remaining quantity after closes. |
| `venue` | `str` | Venue of the opening fill. |
| `source_paths` | `list[str]` | Unique, sorted ledger paths contributing to the lot. |

### Trade Schema

| Field | Type | Description |
| --- | --- | --- |
| `trade_id` | `str` | Deterministic SHA256 hash over stable fields. |
| `symbol` | `str` | Uppercased symbol. |
| `direction` | `str` | `long` or `short` (short trades are currently unsupported). |
| `open_fill_id` | `str` | Opening fill id. |
| `close_fill_id` | `str` | Closing fill id. |
| `open_ts_utc` | `str` | Opening timestamp (UTC). |
| `close_ts_utc` | `str` | Closing timestamp (UTC). |
| `open_date_ny` | `str` | Opening date (NY). |
| `close_date_ny` | `str` | Closing date (NY). |
| `qty` | `float` | Matched quantity for the trade segment. |
| `open_price` | `float \| None` | Opening price, if available. |
| `close_price` | `float \| None` | Closing price, if available. |
| `fees` | `float` | Pro-rated sum of fees from contributing fills. |
| `venue` | `str` | Venue of the opening fill. |
| `notes` | `str \| None` | Notes such as `missing_price_open` / `missing_price_close`. |

### Reconstruction Result Schema

| Field | Type | Description |
| --- | --- | --- |
| `trades` | `list[Trade]` | Matched trade segments in deterministic order. |
| `open_lots` | `list[Lot]` | Remaining open lots in deterministic order. |
| `warnings` | `list[str]` | Deterministic warnings for unsupported scenarios. |
| `source_metadata` | `dict[str, str]` | Metadata carried forward from ingestion. |

## D2-Skeleton Aggregates

Phase D2-Skeleton adds deterministic, read-only aggregates for validation and pipeline health. These aggregates are keyed by `date_ny` (America/New_York) and never include performance evaluation metrics or attribution.

### DailyAggregate Schema

| Field | Type | Description |
| --- | --- | --- |
| `date_ny` | `str` | `YYYY-MM-DD` close date in America/New_York. |
| `trade_count` | `int` | Number of trade segments closed on the date. |
| `closed_qty` | `float` | Sum of trade quantities. |
| `gross_notional_closed` | `float` | Sum of `abs(qty) * close_price` (missing prices contribute `0.0`). |
| `realized_pnl` | `float \| None` | Sum of per-trade realized PnL when all trades have prices; otherwise `None`. |
| `missing_price_trade_count` | `int` | Count of trades missing open or close prices. |
| `fees_total` | `float` | Sum of trade fees (including pro-rata allocations). |
| `symbols_traded` | `list[str]` | Unique, sorted symbols closed on the date. |
| `warnings` | `list[str]` | Stable warnings (`missing_price_in_day`, `contains_short_trades`). |

### CumulativeAggregate Schema

| Field | Type | Description |
| --- | --- | --- |
| `through_date_ny` | `str` | Inclusive end date (America/New_York). |
| `trade_count` | `int` | Cumulative trade segments closed. |
| `closed_qty` | `float` | Cumulative closed quantity. |
| `gross_notional_closed` | `float` | Cumulative gross notional closed. |
| `realized_pnl` | `float \| None` | Cumulative realized PnL when all prior days are known; otherwise `None`. |
| `missing_price_trade_count` | `int` | Cumulative missing-price trade count. |
| `fees_total` | `float` | Cumulative fees. |
| `symbols_traded` | `list[str]` | Unique, sorted symbols across all dates. |

### Explicit Non-goals

- No win rate.
- No expectancy.
- No Sharpe/Sortino.
- No drawdown curves.
- No regime or attribution segmentation.

These aggregates are for pipeline validation, not strategy evaluation.

## Deterministic Ordering

Canonical fills are sorted by:

1. `ts_utc`
2. `symbol`
3. `side`
4. `order_id`
5. `qty`
6. `price` (None sorts last)
7. `fill_id`

Trades are emitted in deterministic order by close timestamp, symbol, open timestamp, open fill id, close fill id, quantity, and trade id. Lots are emitted in deterministic order by open timestamp, symbol, open fill id, remaining quantity, and lot id.

## Matching Policy (FIFO)

- Fills are sorted deterministically and processed in order.
- `buy` fills open/increase long lots.
- `sell` fills close/decrease open long lots using FIFO matching.
- Partial closes split into multiple trade segments when a sell spans multiple open lots.
- Fees are apportioned pro-rata by matched quantity from each contributing fill.

## Limitations

- Short sales are not supported in Phase D1. Sells without open lots emit warnings and do not create trades.
- Corporate actions, broker reconciliation, and cross-venue netting are out of scope.
- Missing prices are retained as `None` and noted on trades for downstream handling.

## Hashing Recipe

`fill_id` is a SHA256 hash of the following string (fields are joined with `|`):

```
venue|order_id|symbol|side|qty|price|ts_utc|source_path|raw_json(optional)
```

`raw_json` is appended only when present (compact JSON with sorted keys). `qty` and `price` are serialized with deterministic float formatting.

`lot_id` is a SHA256 hash of:

```
symbol|side|open_fill_id|open_ts_utc|open_qty|open_price|venue|joined_source_paths
```

`trade_id` is a SHA256 hash of:

```
symbol|direction|open_fill_id|close_fill_id|open_ts_utc|close_ts_utc|qty|open_price|close_price|venue
```

## Supported Ledger Formats

### Dry-run ledger (`state/dry_run_ledger.json`)

Accepted shapes:
- Root object with `entries: []`.
- Root list of entries.
- Root dict of entries (values used as entries).

Required entry fields:
- `symbol`
- `ts` or `timestamp` (ISO 8601 with timezone).

Optional entry fields:
- `order_id` (synthetic id will be used if missing).
- `side`, `qty`, `price`, `fees`.

### Live ledger (`ledger/ALPACA_LIVE/<YYYY-MM-DD>.jsonl`)

Expected shape: JSONL with one entry per line.

Required entry fields:
- `symbol`
- `timestamp` (ISO 8601 with timezone).

Optional entry fields:
- `order_id`, `notional` (used as `qty` when `qty` is missing), `price`, `fees`.

## Timezone Rules

- `ts_utc` is always timezone-aware and in UTC.
- `ts_ny` and `date_ny` are derived using `America/New_York` via stdlib `zoneinfo`.
- Timestamps that lack timezone info are rejected.
