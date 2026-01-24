"""CLI helper for Schwab manual Slack ticket emission."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from execution_v2 import book_ids, book_router
from execution_v2.schwab_manual_adapter import slack_post_enabled


def _load_intents(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text())
    except Exception as exc:
        raise RuntimeError(f"failed to read intents JSON ({type(exc).__name__})") from exc

    if not isinstance(data, list):
        raise ValueError("intents JSON must be a list")
    intents: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("each intent must be an object")
        intents.append(item)
    return intents


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send Schwab manual trade tickets via Slack.")
    parser.add_argument("--ny-date", required=True, help="NY date (YYYY-MM-DD)")
    parser.add_argument("--intents-path", required=True, help="Path to intents JSON list")
    parser.add_argument(
        "--now-utc",
        default=None,
        help="Override UTC timestamp (ISO-8601) for ledger entries",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    intents_path = Path(args.intents_path)
    intents = _load_intents(intents_path)

    now_utc = None
    if args.now_utc:
        now_utc = datetime.fromisoformat(args.now_utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)

    adapter = book_router.select_trading_client(book_ids.SCHWAB_401K_MANUAL)

    if not slack_post_enabled():
        print("SLACK_POST_ENABLED is not set; skipping Slack post and ledger write.")
        return 0

    result = adapter.send_trade_tickets(
        intents,
        ny_date=args.ny_date,
        repo_root=repo_root,
        now_utc=now_utc,
        post_enabled=True,
    )
    print(
        f"Sent {result.sent} Schwab manual tickets for {result.ny_date}. "
        f"Ledger: {result.ledger_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
