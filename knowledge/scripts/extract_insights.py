#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import re
import sqlite3
from typing import Optional

DB_DEFAULT = "knowledge/kb.sqlite"

RULE_WORDS = [
  "must", "should", "avoid", "never", "only", "always", "cannot", "don't", "do not",
  "require", "need to", "if", "when", "unless", "until", "invalid", "wrong", "stop",
  "rule", "mistake", "error"
]

TIMEFRAME_HINTS = {
  "weekly": "weekly",
  "daily": "daily",
  "intraday": "intraday",
  "HTF": "HTF",
  "LTF": "LTF",
  "timeframe": "unknown",
}

TOPIC_PATTERNS = [
  ("liquidity", re.compile(r"\b(liquid|liquidity|spread|slippage|dollar volume|avg(?:erage)? volume|volume profile|thin|market depth|easy (?:in|out)|fills?|trapped|overnight)\b", re.I)),
  ("vwap",      re.compile(r"\bVWAP\b", re.I)),
  ("avwap",     re.compile(r"\bAVWAP\b", re.I)),
  ("structure", re.compile(r"\b(structure|trend|higher high|higher low|lower high|lower low|support|resistance|breakout|base|range|compression|expansion)\b", re.I)),
  ("gaps",      re.compile(r"\b(gap|gaps)\b", re.I)),
  ("risk",      re.compile(r"\b(risk|stop|position size|sizing|invalid|invalidation)\b", re.I)),
]

SENT_SPLIT = re.compile(r"(?<=[\.\?\!])\s+")

def sha12(s: str) -> str:
  return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]

def clean_text(s: str) -> str:
  s = html.unescape(s)
  s = re.sub(r"\s+", " ", s).strip()
  return s

def destutter(s: str) -> str:
  s = clean_text(s)
  words = s.split()
  if len(words) < 20:
    return s
  for n in range(8, 2, -1):
    i = 0
    out = []
    while i < len(words):
      if i + 2*n <= len(words) and words[i:i+n] == words[i+n:i+2*n]:
        out.extend(words[i:i+n])
        j = i + n
        while j + n <= len(words) and words[i:i+n] == words[j:j+n]:
          j += n
        i = j
      else:
        out.append(words[i])
        i += 1
    words = out
  return " ".join(words)

def classify_timeframe(text: str) -> str:
  for k, v in TIMEFRAME_HINTS.items():
    if re.search(rf"\b{k}\b", text, flags=re.I):
      return v
  return "unknown"

def classify_topic(text: str) -> str:
  for topic, pat in TOPIC_PATTERNS:
    if pat.search(text):
      return topic
  return "general"

def classify_type(text: str) -> str:
  t = text.lower()
  if any(w in t for w in ["invalid", "invalidation", "wrong if", "prove me wrong"]):
    return "invalidation"
  if any(w in t for w in ["must", "require", "need to", "cannot", "never", "do not", "don't", "avoid", "rule", "mistake", "error"]):
    return "constraint"
  if any(w in t for w in ["prefer", "i like", "i want", "i tend to", "i usually"]):
    return "preference"
  if any(w in t for w in ["means", "is when", "definition of"]):
    return "definition"
  return "process"

def score_sentence(text: str) -> float:
  t = text.lower()
  score = 0.0
  for w in RULE_WORDS:
    if w in t:
      score += 1.0
  topic = classify_topic(text)
  if topic in ("liquidity", "vwap", "avwap", "structure", "risk", "gaps"):
    score += 1.5
  n = len(text)
  if n < 50:
    score -= 1.0
  if n > 280:
    score -= 0.5
  return score

def main(db: str, source: Optional[str], min_score: float, min_score_universe: float, limit_blocks: Optional[int]) -> None:
  con = sqlite3.connect(db)
  try:
    if source:
      rows = con.execute(
        "SELECT block_id, source_id, ordinal, text FROM normalized_blocks WHERE source_id=? ORDER BY ordinal",
        (source,),
      ).fetchall()
    else:
      q = "SELECT block_id, source_id, ordinal, text FROM normalized_blocks ORDER BY source_id, ordinal"
      if limit_blocks:
        q += f" LIMIT {int(limit_blocks)}"
      rows = con.execute(q).fetchall()

    inserted = 0
    for block_id, source_id, ordinal, block_text in rows:
      block_text = destutter(block_text)
      sentences = SENT_SPLIT.split(block_text)

      seen = set()
      for sent in sentences:
        sent = destutter(sent)
        sent = clean_text(sent)
        if len(sent) < 25:
          continue
        key = sent.lower()
        if key in seen:
          continue
        seen.add(key)

        topic = classify_topic(sent)
        sc = score_sentence(sent)

        if topic in ("liquidity", "vwap", "avwap", "structure", "gaps"):
          if sc < min_score_universe:
            continue
        else:
          if sc < min_score:
            continue

        tf = classify_timeframe(sent)
        itype = classify_type(sent)
        low = sent.lower()
        confidence = "explicit" if any(x in low for x in ["must", "never", "do not", "don't", "only", "require", "need to", "mistake", "error"]) else "inferred"

        insight_id = f"i_{sha12(source_id + '|' + block_id + '|' + sent)}"
        con.execute(
          """
          INSERT OR REPLACE INTO atomic_insights
            (insight_id, source_id, block_id, ordinal, insight_type, timeframe, topic, text, confidence, score)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (insight_id, source_id, block_id, int(ordinal), itype, tf, topic, sent, confidence, float(sc)),
        )
        inserted += 1

    con.commit()
    print(f"atomic_insights upserted={inserted} thresholds: general>={min_score}, universe>={min_score_universe}")
  finally:
    con.close()

if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("--db", default=DB_DEFAULT)
  ap.add_argument("--source", default=None)
  ap.add_argument("--min-score", type=float, default=3.0)
  ap.add_argument("--min-score-universe", type=float, default=2.5)
  ap.add_argument("--limit-blocks", type=int, default=None)
  args = ap.parse_args()
  main(args.db, args.source, args.min_score, args.min_score_universe, args.limit_blocks)
