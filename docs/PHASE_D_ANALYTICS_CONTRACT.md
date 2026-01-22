# Phase D0 Analytics Contract

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

## Deterministic Ordering

Canonical fills are sorted by:

1. `ts_utc`
2. `symbol`
3. `side`
4. `order_id`
5. `qty`
6. `price` (None sorts last)
7. `fill_id`

## Hashing Recipe

`fill_id` is a SHA256 hash of the following string (fields are joined with `|`):

```
venue|order_id|symbol|side|qty|price|ts_utc|source_path|raw_json(optional)
```

`raw_json` is appended only when present (compact JSON with sorted keys). `qty` and `price` are serialized with deterministic float formatting.

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

### Live ledger (`state/live_orders_today.json`)

Expected shape:

```
{
  "date_ny": "YYYY-MM-DD",
  "entries": [ ... ]
}
```

Required entry fields:
- `symbol`
- `timestamp` (ISO 8601 with timezone).

Optional entry fields:
- `order_id`, `notional` (used as `qty` when `qty` is missing), `price`, `fees`.

## Timezone Rules

- `ts_utc` is always timezone-aware and in UTC.
- `ts_ny` and `date_ny` are derived using `America/New_York` via stdlib `zoneinfo`.
- Timestamps that lack timezone info are rejected.
