#!/usr/bin/env python3
from __future__ import annotations
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS sources (
  source_id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,          -- youtube | blog
  url TEXT NOT NULL,
  title TEXT,
  published_at TEXT,
  metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS raw_blocks (
  block_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  ordinal INTEGER NOT NULL,
  ts_start REAL,
  ts_end REAL,
  text TEXT NOT NULL,
  FOREIGN KEY(source_id) REFERENCES sources(source_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_blocks_source ON raw_blocks(source_id, ordinal);
"""

def init_db(db_path: str) -> None:
  Path(db_path).parent.mkdir(parents=True, exist_ok=True)
  con = sqlite3.connect(db_path)
  try:
    con.executescript(SCHEMA)
    con.commit()
  finally:
    con.close()

if __name__ == "__main__":
  import sys
  if len(sys.argv) != 2:
    raise SystemExit("Usage: kb_init.py <db_path>")
  init_db(sys.argv[1])
  print(f"Initialized {sys.argv[1]}")
