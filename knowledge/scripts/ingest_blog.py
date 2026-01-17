#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Optional

import trafilatura
from trafilatura.settings import use_config

DB_DEFAULT = "knowledge/kb.sqlite"

def sha12(s: str) -> str:
  return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

def slugify(url: str, max_len: int = 80) -> str:
  s = url.lower()
  s = re.sub(r"https?://", "", s)
  s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
  return s[:max_len] if s else "article"

def upsert_source(con: sqlite3.Connection, source_id: str, url: str, title: Optional[str], published_at: Optional[str], metadata: dict) -> None:
  con.execute(
    """
    INSERT INTO sources (source_id, source_type, url, title, published_at, metadata_json)
    VALUES (?, 'blog', ?, ?, ?, ?)
    ON CONFLICT(source_id) DO UPDATE SET
      url=excluded.url,
      title=COALESCE(excluded.title, sources.title),
      published_at=COALESCE(excluded.published_at, sources.published_at),
      metadata_json=excluded.metadata_json
    """,
    (source_id, url, title, published_at, json.dumps(metadata, ensure_ascii=False)),
  )

def insert_blocks(con: sqlite3.Connection, source_id: str, paragraphs: list[str]) -> int:
  inserted = 0
  for i, p in enumerate([x.strip() for x in paragraphs if x.strip()], start=1):
    block_id = f"bl_{source_id}_{i:06d}"
    con.execute(
      """
      INSERT OR REPLACE INTO raw_blocks (block_id, source_id, ordinal, ts_start, ts_end, text)
      VALUES (?, ?, ?, NULL, NULL, ?)
      """,
      (block_id, source_id, i, p),
    )
    inserted += 1
  return inserted

def ingest(db_path: str, links_file: str, out_dir: str) -> None:
  out = Path(out_dir)
  out.mkdir(parents=True, exist_ok=True)

  urls = [ln.strip() for ln in Path(links_file).read_text(encoding="utf-8").splitlines()
          if ln.strip() and not ln.strip().startswith("#")]

  cfg = use_config()
  cfg.set("DEFAULT", "EXTRACTION_TIMEOUT", "30")
  cfg.set("DEFAULT", "MIN_EXTRACTED_SIZE", "250")

  con = sqlite3.connect(db_path)
  try:
    for idx, url in enumerate(urls, start=1):
      downloaded = trafilatura.fetch_url(url)
      if not downloaded:
        print(f"[{idx}/{len(urls)}] FAIL download {url}")
        continue

      text = trafilatura.extract(
        downloaded,
        config=cfg,
        output_format="txt",
        include_tables=True,
        include_comments=False,
        favor_precision=True,
      )

      if not text or len(text.strip()) < 200:
        print(f"[{idx}/{len(urls)}] SKIP small/empty extract {url}")
        continue

      sid = f"bl_{sha12(url)}"
      fn = f"{sid}__{slugify(url)}.txt"
      (out / fn).write_text(text.strip() + "\n", encoding="utf-8")

      paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
      metadata = {"fetched_at": int(time.time()), "filename": fn}
      upsert_source(con, sid, url, title=None, published_at=None, metadata=metadata)
      inserted = insert_blocks(con, sid, paragraphs)
      con.commit()

      print(f"[{idx}/{len(urls)}] {sid} paragraphs_inserted={inserted} file={fn}")
  finally:
    con.close()

if __name__ == "__main__":
  import argparse
  ap = argparse.ArgumentParser()
  ap.add_argument("--db", default=DB_DEFAULT)
  ap.add_argument("--links", default="knowledge/inputs/blog_links.txt")
  ap.add_argument("--outdir", default="knowledge/raw/blog")
  args = ap.parse_args()
  ingest(args.db, args.links, args.outdir)
