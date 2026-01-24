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
- `SCHWAB_401K_MANUAL` — Manual Schwab 401(k) book (placeholder only; no broker adapter wired).
