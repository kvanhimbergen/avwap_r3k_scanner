from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from analytics.io.ledgers import parse_dry_run_ledger

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analytics"


def test_json_determinism() -> None:
    first = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_min.json"))
    second = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_min.json"))

    first_json = json.dumps([asdict(fill) for fill in first.fills], sort_keys=True)
    second_json = json.dumps([asdict(fill) for fill in second.fills], sort_keys=True)

    assert first_json == second_json
