"""Tests for tools.log_fills — manual RAEC 401(k) fill logger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.log_fills import (
    DEFAULT_STRATEGY,
    LEDGER_SUBDIR,
    RECORD_TYPE,
    SCHEMA_VERSION,
    ParsedFill,
    append_records,
    build_manual_fill_id,
    load_existing_fill_ids,
    main,
    parse_fill,
    _ledger_path,
    _stable_json_dumps,
)


# ---------------------------------------------------------------------------
# parse_fill
# ---------------------------------------------------------------------------

class TestParseFill:
    def test_basic_buy(self):
        f = parse_fill("BUY XLI 100@132.50")
        assert f == ParsedFill(side="BUY", symbol="XLI", qty=100.0, price=132.5)

    def test_basic_sell(self):
        f = parse_fill("SELL BIL 200@91.20")
        assert f == ParsedFill(side="SELL", symbol="BIL", qty=200.0, price=91.2)

    def test_case_insensitive(self):
        f = parse_fill("buy smh 50@245.30")
        assert f.side == "BUY"
        assert f.symbol == "SMH"
        assert f.qty == 50.0
        assert f.price == 245.3

    def test_qty_optional(self):
        f = parse_fill("BUY XLI @132.50")
        assert f.qty is None
        assert f.price == 132.5

    def test_fractional_qty(self):
        f = parse_fill("BUY TQQQ 10.5@65.00")
        assert f.qty == 10.5
        assert f.price == 65.0

    def test_fractional_price(self):
        f = parse_fill("SELL VTI 1@432.123")
        assert f.price == 432.123

    def test_whitespace_around_at(self):
        f = parse_fill("BUY XLI 100 @ 132.50")
        assert f == ParsedFill(side="BUY", symbol="XLI", qty=100.0, price=132.5)

    def test_leading_trailing_whitespace(self):
        f = parse_fill("  BUY XLI 100@132.50  ")
        assert f.symbol == "XLI"

    def test_invalid_missing_price(self):
        with pytest.raises(ValueError, match="invalid fill string"):
            parse_fill("BUY XLI 100")

    def test_invalid_missing_side(self):
        with pytest.raises(ValueError, match="invalid fill string"):
            parse_fill("XLI 100@132.50")

    def test_invalid_bad_side(self):
        with pytest.raises(ValueError, match="invalid fill string"):
            parse_fill("HOLD XLI 100@132.50")

    def test_invalid_empty(self):
        with pytest.raises(ValueError, match="invalid fill string"):
            parse_fill("")


# ---------------------------------------------------------------------------
# build_manual_fill_id
# ---------------------------------------------------------------------------

class TestBuildManualFillId:
    def test_deterministic(self):
        kwargs = dict(
            date_ny="2026-02-17",
            book_id="SCHWAB_401K_MANUAL",
            strategy_id="RAEC_401K_COORD",
            symbol="XLI",
            side="BUY",
            qty=100.0,
            price=132.5,
        )
        id1 = build_manual_fill_id(**kwargs)
        id2 = build_manual_fill_id(**kwargs)
        assert id1 == id2
        assert len(id1) == 64

    def test_different_symbol_different_id(self):
        base = dict(
            date_ny="2026-02-17",
            book_id="SCHWAB_401K_MANUAL",
            strategy_id="RAEC_401K_COORD",
            side="BUY",
            qty=100.0,
            price=132.5,
        )
        id1 = build_manual_fill_id(symbol="XLI", **base)
        id2 = build_manual_fill_id(symbol="SMH", **base)
        assert id1 != id2

    def test_different_price_different_id(self):
        base = dict(
            date_ny="2026-02-17",
            book_id="SCHWAB_401K_MANUAL",
            strategy_id="RAEC_401K_COORD",
            symbol="XLI",
            side="BUY",
            qty=100.0,
        )
        id1 = build_manual_fill_id(price=132.5, **base)
        id2 = build_manual_fill_id(price=133.0, **base)
        assert id1 != id2

    def test_none_qty_vs_zero_qty(self):
        base = dict(
            date_ny="2026-02-17",
            book_id="SCHWAB_401K_MANUAL",
            strategy_id="RAEC_401K_COORD",
            symbol="XLI",
            side="BUY",
            price=132.5,
        )
        id_none = build_manual_fill_id(qty=None, **base)
        id_zero = build_manual_fill_id(qty=0.0, **base)
        assert id_none != id_zero


# ---------------------------------------------------------------------------
# load_existing_fill_ids
# ---------------------------------------------------------------------------

class TestLoadExistingFillIds:
    def test_missing_file(self, tmp_path: Path):
        ids = load_existing_fill_ids(tmp_path / "nonexistent.jsonl")
        assert ids == set()

    def test_empty_file(self, tmp_path: Path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        ids = load_existing_fill_ids(p)
        assert ids == set()

    def test_reads_fill_ids(self, tmp_path: Path):
        p = tmp_path / "day.jsonl"
        records = [
            {"fill_id": "aaa", "symbol": "XLI"},
            {"fill_id": "bbb", "symbol": "SMH"},
        ]
        p.write_text("\n".join(json.dumps(r) for r in records) + "\n")
        ids = load_existing_fill_ids(p)
        assert ids == {"aaa", "bbb"}


# ---------------------------------------------------------------------------
# append_records / ledger format
# ---------------------------------------------------------------------------

class TestAppendRecords:
    def test_creates_file_and_dirs(self, tmp_path: Path):
        p = tmp_path / "sub" / "dir" / "day.jsonl"
        records = [{"fill_id": "abc", "symbol": "XLI"}]
        append_records(p, records)
        assert p.exists()
        lines = p.read_text().strip().split("\n")
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"fill_id": "abc", "symbol": "XLI"}

    def test_appends_to_existing(self, tmp_path: Path):
        p = tmp_path / "day.jsonl"
        p.write_text('{"fill_id":"old"}\n')
        append_records(p, [{"fill_id": "new"}])
        lines = p.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["fill_id"] == "old"
        assert json.loads(lines[1])["fill_id"] == "new"

    def test_sorted_keys(self, tmp_path: Path):
        p = tmp_path / "day.jsonl"
        append_records(p, [{"z": 1, "a": 2}])
        raw = p.read_text().strip()
        assert raw == '{"a":2,"z":1}'

    def test_compact_json(self, tmp_path: Path):
        p = tmp_path / "day.jsonl"
        append_records(p, [{"key": "value", "num": 42}])
        raw = p.read_text().strip()
        assert " " not in raw  # compact separators


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def _run(self, tmp_path: Path, fills: list[str], **extra_args: str) -> tuple[int, Path]:
        argv = ["--date", "2026-02-17", "--repo-root", str(tmp_path),
                "--now-utc", "2026-02-17T15:30:00+00:00"] + list(extra_args.values()) + fills
        # flatten extra_args as flag pairs
        flat_argv = ["--date", "2026-02-17", "--repo-root", str(tmp_path),
                      "--now-utc", "2026-02-17T15:30:00+00:00"]
        for k, v in extra_args.items():
            flat_argv.extend([k, v])
        flat_argv.extend(fills)
        rc = main(flat_argv)
        path = tmp_path / "ledger" / LEDGER_SUBDIR / "2026-02-17.jsonl"
        return rc, path

    def test_idempotent_rerun(self, tmp_path: Path):
        fills = ["BUY XLI 100@132.50"]
        rc1, path = self._run(tmp_path, fills)
        assert rc1 == 0
        count1 = len(path.read_text().strip().split("\n"))
        rc2, _ = self._run(tmp_path, fills)
        assert rc2 == 0
        count2 = len(path.read_text().strip().split("\n"))
        assert count1 == count2 == 1

    def test_different_fills_both_written(self, tmp_path: Path):
        rc1, path = self._run(tmp_path, ["BUY XLI 100@132.50"])
        assert rc1 == 0
        rc2, _ = self._run(tmp_path, ["BUY SMH 50@245.30"])
        assert rc2 == 0
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# CLI end-to-end
# ---------------------------------------------------------------------------

class TestCLI:
    def test_happy_path(self, tmp_path: Path):
        argv = [
            "--date", "2026-02-17",
            "--repo-root", str(tmp_path),
            "--now-utc", "2026-02-17T15:30:00+00:00",
            "BUY XLI 100@132.50",
            "SELL BIL 200@91.20",
        ]
        rc = main(argv)
        assert rc == 0
        path = tmp_path / "ledger" / LEDGER_SUBDIR / "2026-02-17.jsonl"
        assert path.exists()
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        r = json.loads(lines[0])
        assert r["record_type"] == RECORD_TYPE
        assert r["schema_version"] == SCHEMA_VERSION
        assert r["book_id"] == "SCHWAB_401K_MANUAL"
        assert r["strategy_id"] == DEFAULT_STRATEGY
        assert r["side"] == "BUY"
        assert r["symbol"] == "XLI"
        assert r["qty"] == 100.0
        assert r["price"] == 132.5
        assert r["fees"] == 0.0
        assert r["notes"] is None
        assert r["ts_utc"] == "2026-02-17T15:30:00+00:00"
        assert len(r["fill_id"]) == 64

    def test_options_propagation(self, tmp_path: Path):
        argv = [
            "--date", "2026-02-17",
            "--repo-root", str(tmp_path),
            "--now-utc", "2026-02-17T15:30:00+00:00",
            "--strategy", "RAEC_401K_V3",
            "--fees", "4.95",
            "--notes", "morning session",
            "BUY TQQQ 50@65.00",
        ]
        rc = main(argv)
        assert rc == 0
        path = tmp_path / "ledger" / LEDGER_SUBDIR / "2026-02-17.jsonl"
        r = json.loads(path.read_text().strip())
        assert r["strategy_id"] == "RAEC_401K_V3"
        assert r["fees"] == 4.95
        assert r["notes"] == "morning session"

    def test_bad_date(self, tmp_path: Path):
        argv = [
            "--date", "not-a-date",
            "--repo-root", str(tmp_path),
            "BUY XLI 100@132.50",
        ]
        rc = main(argv)
        assert rc == 1

    def test_bad_fill(self, tmp_path: Path):
        argv = [
            "--date", "2026-02-17",
            "--repo-root", str(tmp_path),
            "INVALID FILL STRING",
        ]
        rc = main(argv)
        assert rc == 1

    def test_price_only_no_qty(self, tmp_path: Path):
        argv = [
            "--date", "2026-02-17",
            "--repo-root", str(tmp_path),
            "--now-utc", "2026-02-17T15:30:00+00:00",
            "BUY XLI @132.50",
        ]
        rc = main(argv)
        assert rc == 0
        path = tmp_path / "ledger" / LEDGER_SUBDIR / "2026-02-17.jsonl"
        r = json.loads(path.read_text().strip())
        assert r["qty"] is None
        assert r["price"] == 132.5

    def test_ledger_path_structure(self, tmp_path: Path):
        argv = [
            "--date", "2026-02-17",
            "--repo-root", str(tmp_path),
            "--now-utc", "2026-02-17T15:30:00+00:00",
            "BUY XLI 100@132.50",
        ]
        main(argv)
        expected = tmp_path / "ledger" / LEDGER_SUBDIR / "2026-02-17.jsonl"
        assert expected.exists()
