# Portfolio Decision Contract (Schema v1.0)

## Purpose
The portfolio decision contract is an append-only JSONL ledger written **once per execution cycle**.
It captures inputs, intents, gates, and actions for each loop iteration, forming the audit spine for
replay and analytics in later phases.

## Location
Records are written daily (NY date) to:

```
ledger/PORTFOLIO_DECISIONS/<YYYY-MM-DD>.jsonl
```

Each line is a single JSON object. The serializer uses sorted keys and stable ordering for nested
lists to keep the output deterministic.

## Schema
- `schema_version`: `"1.0"`
- `decision_id`: stable hash for the cycle
- `ts_utc`: RFC3339 UTC timestamp of the decision
- `ny_date`: NY local date (`YYYY-MM-DD`)
- `cycle`: execution metadata (loop interval, service name, pid, hostname)
- `mode`: execution mode and DRY_RUN override status
- `inputs`: candidates snapshot, account snapshot, constraint snapshot
- `intents`: intent count and projected intents
- `gates`: market, freshness, live gate status, and any blocks
- `actions`: submitted orders, skipped items, errors
- `artifacts`: ledger paths written and the portfolio decision path

## Replay intent
Downstream phases can replay decisions deterministically from this ledger without mutating past
records, ensuring a durable audit trail for allocation and analytics tooling.
