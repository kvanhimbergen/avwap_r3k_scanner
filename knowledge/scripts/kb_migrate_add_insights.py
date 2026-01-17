#!/usr/bin/env python3
from __future__ import annotations
import sqlite3

DB_DEFAULT = "knowledge/kb.sqlite"

SQL = """
CREATE TABLE IF NOT EXISTS atomic_insights (
  insight_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  block_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  insight_type TEXT NOT NULL,       -- constraint | preference | invalidation | definition | process
  timeframe TEXT,                  -- HTF | LTF | daily | weekly | intraday | unknown
  topic TEXT,                      -- liquidity | vwap | avwap | structure | risk | gaps | general
  text TEXT NOT NULL,              -- the extracted insight sentence (normalized)
  confidence TEXT NOT NULL,         -- explicit | inferred
  score REAL NOT NULL,              -- heuristic score
  FOREIGN KEY(block_id) REFERENCES raw_blocks(block_id),
  FOREIGN KEY(source_id) REFERENCES sources(source_id)
);

CREATE INDEX IF NOT EXISTS idx_insights_source ON atomic_insights(source_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_insights_topic ON atomic_insights(topic);
"""

def main(db_path: str) -> None:
  con = sqlite3.connect(db_path)
  try:
    con.executescript(SQL)
    con.commit()
    print("Migration complete: atomic_insights")
  finally:
    con.close()

if __name__ == "__main__":
  import argparse
  ap = argparse.ArgumentParser()
  ap.add_argument("--db", default=DB_DEFAULT)
  args = ap.parse_args()
  main(args.db)
