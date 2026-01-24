# Book IDs and Ledgers

## What is a `book_id`?
A `book_id` identifies an isolated execution book (venue + rules + ledger). Ledgers are book-scoped so
multiple books can run side-by-side without cross-talk.

## Ledger path convention
All book ledgers use:
```
ledger/<book_id>/<YYYY-MM-DD>.jsonl
```

## Defined books
- `ALPACA_PAPER` — Alpaca paper trading (broker-integrated paper execution).
- `ALPACA_LIVE` — Alpaca live trading (production execution).
- `SCHWAB_401K_MANUAL` — Manual Schwab 401(k) book (Slack ticket adapter; no broker client).

## Schwab manual book notes
- Ledger path: `ledger/SCHWAB_401K_MANUAL/<YYYY-MM-DD>.jsonl`
- Idempotency: tickets are keyed by deterministic `intent_id`; re-runs skip `MANUAL_TICKET_SENT` intents found in the ledger.
- CLI smoke runner: see `docs/SCHWAB_MANUAL.md` for safe usage (`SLACK_POST_ENABLED=1` required).
- Read-only snapshots + reconciliation: see `docs/SCHWAB_READONLY.md` (fixture-backed; no execution wiring).
