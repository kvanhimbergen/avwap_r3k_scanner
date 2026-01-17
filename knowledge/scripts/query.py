#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from textwrap import shorten

DB_DEFAULT = "knowledge/kb.sqlite"

def main() -> None:
  ap = argparse.ArgumentParser(description="Query KB raw_blocks by keyword/source.")
  ap.add_argument("--db", default=DB_DEFAULT)
  ap.add_argument("--q", required=True, help="keyword (case-insensitive substring match)")
  ap.add_argument("--source", default=None, help="source_id filter (e.g., yt_jalxRNlYCmA)")
  ap.add_argument("--limit", type=int, default=25)
  args = ap.parse_args()

  con = sqlite3.connect(args.db)
  try:
    q = f"%{args.q.lower()}%"
    if args.source:
      rows = con.execute(
        """
        SELECT rb.block_id, rb.source_id, rb.ordinal, rb.text
        FROM raw_blocks rb
        WHERE rb.source_id = ?
          AND lower(rb.text) LIKE ?
        ORDER BY rb.source_id, rb.ordinal
        LIMIT ?
        """,
        (args.source, q, args.limit),
      ).fetchall()
    else:
      rows = con.execute(
        """
        SELECT rb.block_id, rb.source_id, rb.ordinal, rb.text
        FROM raw_blocks rb
        WHERE lower(rb.text) LIKE ?
        ORDER BY rb.source_id, rb.ordinal
        LIMIT ?
        """,
        (q, args.limit),
      ).fetchall()

    for block_id, source_id, ordinal, text in rows:
      preview = shorten(text.replace("\n", " "), width=200, placeholder="…")
      print(f"{block_id} | {source_id} | #{ordinal} | {preview}")
    print(f"\nrows={len(rows)}")
  finally:
    con.close()

if __name__ == "__main__":
  main()
