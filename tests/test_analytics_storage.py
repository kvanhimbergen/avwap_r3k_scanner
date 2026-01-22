from __future__ import annotations

import json
from pathlib import Path

from analytics.io.ledgers import parse_dry_run_ledger
from analytics.reconstruction import reconstruct_trades
from analytics.storage import serialize_reconstruction, write_reconstruction_json


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analytics"


def _build_reconstruction():
    result = parse_dry_run_ledger(str(FIXTURES_DIR / "dry_run_ledger_reconstruction.json"))
    return reconstruct_trades(result.fills)


def test_serialize_reconstruction_deterministic() -> None:
    reconstruction = _build_reconstruction()
    payload_first = serialize_reconstruction(reconstruction)
    payload_second = serialize_reconstruction(reconstruction)

    serialized_first = json.dumps(payload_first, sort_keys=True, separators=(",", ":"))
    serialized_second = json.dumps(payload_second, sort_keys=True, separators=(",", ":"))

    assert serialized_first == serialized_second


def test_write_reconstruction_json(tmp_path: Path) -> None:
    reconstruction = _build_reconstruction()
    payload = serialize_reconstruction(reconstruction)
    expected = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    output_path = tmp_path / "reconstruction.json"
    write_reconstruction_json(str(output_path), reconstruction)

    assert output_path.read_text() == expected
