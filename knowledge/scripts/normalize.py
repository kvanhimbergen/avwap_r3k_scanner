#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3

DB_DEFAULT = "knowledge/kb.sqlite"

REPLACEMENTS = [
  (re.compile(r"\banchored\s+vwap\b", re.I), "AVWAP"),
  (re.compile(r"\bvwap\b", re.I), "VWAP"),
  (re.compile(r"\bhigher\s+timeframe\b", re.I), "HTF"),
  (re.compile(r"\blower\s+timeframe\b", re.I), "LTF"),
  (re.compile(r"\brelative\s+volume\b", re.I), "RVOL"),
  (re.compile(r"\brelative\s+strength\b", re.I), "RS"),
]

FILLER_PATTERNS = [
  re.compile(r"\b(you know|kind of|sort of|right\?|okay\?|um|uh)\b", re.I),
]

def normalize_text(s: str) -> str:
  s = s.replace("\r\n", "\n").replace("\r", "\n")
  s = re.sub(r"\s+", " ", s).strip()
  for pat in FILLER_PATTERNS:
    s = pat.sub("", s)
    s = re.sub(r"\s+", " ", s).strip()
  for pat, rep in REPLACEMENTS:
    s = pat.sub(rep, s)
  s = re.sub(r"\s+", " ", s).strip()
  return s

def main(db: str, source: str | None, limit: int | None) -> None:
  con = sqlite3.connect(db)
  try:
    if source:
      rows = con.execute(
        "SELECT block_id, source_id, ordinal, text FROM raw_blocks WHERE source_id=? ORDER BY ordinal",
        (source,),
      ).fetchall()
    else:
      q = "SELECT block_id, source_id, ordinal, text FROM raw_blocks ORDER BY source_id, ordinal"
      if limit:
        q += f" LIMIT {int(limit)}"
      rows = con.execute(q).fetchall()

    upserts = 0
    for block_id, source_id, ordinal, text in rows:
      nt = normalize_text(text)
      norm_id = f"n_{block_id}"
      con.execute(
        """
        INSERT INTO normalized_blocks (norm_id, block_id, source_id, ordinal, text)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(norm_id) DO UPDATE SET text=excluded.text
        """,
        (norm_id, block_id, source_id, ordinal, nt),
      )
      upserts += 1

    con.commit()
    print(f"normalized_blocks upserted={upserts}")
  finally:
    con.close()

if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("--db", default=DB_DEFAULT)
  ap.add_argument("--source", default=None, help="optional source_id to normalize")
  ap.add_argument("--limit", type=int, default=None, help="optional limit (debug)")
  args = ap.parse_args()
  main(args.db, args.source, args.limit)
