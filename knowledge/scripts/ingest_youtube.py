#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

DB_DEFAULT = "knowledge/kb.sqlite"

YOUTUBE_ID_RE = re.compile(r"(?:v=|/)([A-Za-z0-9_-]{11})(?:[?&].*)?$")

def sha12(s: str) -> str:
  return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

def parse_video_id(url: str) -> str:
  m = YOUTUBE_ID_RE.search(url.strip())
  if not m:
    raise ValueError(f"Could not parse YouTube video id from: {url}")
  return m.group(1)

def run(cmd: list[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
  p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
  return p.returncode, p.stdout, p.stderr

def vtt_to_lines(vtt_text: str) -> list[str]:
  s = re.sub(r"^\ufeff?WEBVTT.*?\n\n", "", vtt_text, flags=re.S)
  s = re.sub(r"\d{2}:\d{2}:\d{2}\.\d{3}\s-->\s.*?\n", "", s)
  s = re.sub(r"^\d+\s*$", "", s, flags=re.M)
  s = re.sub(r"<[^>]+>", "", s)
  lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
  return lines

def chunk_lines(lines: list[str], chunk_size: int = 8) -> list[str]:
  chunks = []
  buf: list[str] = []
  for ln in lines:
    buf.append(ln)
    if len(buf) >= chunk_size:
      chunks.append(" ".join(buf))
      buf = []
  if buf:
    chunks.append(" ".join(buf))
  return chunks

@dataclass
class TranscriptArtifact:
  video_id: str
  url: str
  title: Optional[str]
  vtt_path: Optional[Path]
  text_chunks: list[str]
  metadata: dict

def fetch_captions(video_url: str, out_dir: Path) -> TranscriptArtifact:
  out_dir.mkdir(parents=True, exist_ok=True)
  vid = parse_video_id(video_url)
  tmpl = str(out_dir / f"{vid}.%(ext)s")

  # Prefer creator captions, then auto captions
  cmd1 = [
    "yt-dlp",
    "--skip-download",
    "--write-subs",
    "--sub-lang", "en",
    "--sub-format", "vtt",
    "-o", tmpl,
    video_url,
  ]
  rc1, _, _ = run(cmd1)

  cmd2 = [
    "yt-dlp",
    "--skip-download",
    "--write-auto-subs",
    "--sub-lang", "en",
    "--sub-format", "vtt",
    "-o", tmpl,
    video_url,
  ]
  rc2, _, _ = run(cmd2)

  candidates = sorted(out_dir.glob(f"{vid}*.vtt"))
  vtt_path = candidates[0] if candidates else None

  cmd_meta = ["yt-dlp", "-J", video_url]
  rc3, meta_out, _ = run(cmd_meta)
  meta = {}
  if rc3 == 0 and meta_out.strip():
    try:
      meta = json.loads(meta_out)
    except Exception:
      meta = {}
  title = meta.get("title")
  upload_date = meta.get("upload_date")  # YYYYMMDD
  published_at = None
  if isinstance(upload_date, str) and len(upload_date) == 8:
    published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"

  chunks: list[str] = []
  if vtt_path and vtt_path.exists():
    txt = vtt_path.read_text(encoding="utf-8", errors="ignore")
    lines = vtt_to_lines(txt)
    chunks = chunk_lines(lines, chunk_size=8)

  metadata = {
    "yt_dlp_write_subs_rc": rc1,
    "yt_dlp_write_auto_subs_rc": rc2,
    "published_at": published_at,
    "title": title,
    "webpage_url": meta.get("webpage_url"),
    "channel": meta.get("channel"),
    "uploader": meta.get("uploader"),
    "duration": meta.get("duration"),
  }

  return TranscriptArtifact(
    video_id=vid,
    url=video_url,
    title=title,
    vtt_path=vtt_path,
    text_chunks=chunks,
    metadata=metadata,
  )

def upsert_source(con: sqlite3.Connection, source_id: str, url: str, title: Optional[str], published_at: Optional[str], metadata: dict) -> None:
  con.execute(
    """
    INSERT INTO sources (source_id, source_type, url, title, published_at, metadata_json)
    VALUES (?, 'youtube', ?, ?, ?, ?)
    ON CONFLICT(source_id) DO UPDATE SET
      url=excluded.url,
      title=COALESCE(excluded.title, sources.title),
      published_at=COALESCE(excluded.published_at, sources.published_at),
      metadata_json=excluded.metadata_json
    """,
    (source_id, url, title, published_at, json.dumps(metadata, ensure_ascii=False)),
  )

def insert_blocks(con: sqlite3.Connection, source_id: str, chunks: list[str]) -> int:
  inserted = 0
  for i, text in enumerate(chunks, start=1):
    block_id = f"yb_{source_id}_{i:06d}"
    con.execute(
      """
      INSERT OR REPLACE INTO raw_blocks (block_id, source_id, ordinal, ts_start, ts_end, text)
      VALUES (?, ?, ?, NULL, NULL, ?)
      """,
      (block_id, source_id, i, text),
    )
    inserted += 1
  return inserted

def ingest(db_path: str, links_file: str, out_dir: str) -> None:
  out_dir_p = Path(out_dir)
  urls = [ln.strip() for ln in Path(links_file).read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]

  con = sqlite3.connect(db_path)
  try:
    for idx, url in enumerate(urls, start=1):
      art = fetch_captions(url, out_dir_p)
      source_id = f"yt_{art.video_id}"
      published_at = art.metadata.get("published_at")
      upsert_source(con, source_id, art.url, art.title, published_at, art.metadata)
      inserted = insert_blocks(con, source_id, art.text_chunks)
      con.commit()
      print(f"[{idx}/{len(urls)}] {source_id} chunks_inserted={inserted} vtt={'yes' if art.vtt_path else 'no'} title={art.title!r}")
      if inserted == 0:
        print(f"  NOTE: No captions found for {url}. Whisper fallback can be added if needed.")
  finally:
    con.close()

if __name__ == "__main__":
  import argparse
  ap = argparse.ArgumentParser()
  ap.add_argument("--db", default=DB_DEFAULT)
  ap.add_argument("--links", default="knowledge/inputs/youtube_links.txt")
  ap.add_argument("--outdir", default="knowledge/raw/youtube")
  args = ap.parse_args()
  ingest(args.db, args.links, args.outdir)
