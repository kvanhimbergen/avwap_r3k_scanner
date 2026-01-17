#!/usr/bin/env python3
from __future__ import annotations
import sqlite3

DB_DEFAULT = "knowledge/kb.sqlite"

SQL = """
CREATE TABLE IF NOT EXISTS normalized_blocks (
  norm_id TEXT PRIMARY KEY,
  block_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  FOREIGN KEY(block_id) REFERENCES raw_blocks(block_id),
  FOREIGN KEY(source_id) REFERENCES sources(source_id)
);

CREATE INDEX IF NOT EXISTS idx_norm_source_ordinal ON normalized_blocks(source_id, ordinal);
"""

def main(db_path: str) -> None:
  con = sqlite3.connect(db_path)
  try:
    con.executescript(SQL)
    con.commit()
    print("Migration complete: normalized_blocks")
  finally:
    con.close()

if __name__ == "__main__":
  import argparse
  ap = argparse.ArgumentParser()
  ap.add_argument("--db", default=DB_DEFAULT)
  args = ap.parse_args()
  main(args.db)
