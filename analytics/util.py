from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional
from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()


def normalize_side(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"buy", "sell"}:
        return raw
    return "unknown"


def parse_timestamp(value: Any, *, source_path: str, entry_index: int) -> datetime:
    if value is None:
        raise ValueError(f"missing timestamp at index {entry_index} in {source_path}")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise ValueError(f"missing timestamp at index {entry_index} in {source_path}")
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                f"invalid timestamp '{raw}' at index {entry_index} in {source_path}"
            ) from exc
        if dt.tzinfo is None:
            raise ValueError(
                f"timestamp missing timezone at index {entry_index} in {source_path}"
            )
        return dt.astimezone(timezone.utc)
    raise ValueError(
        f"invalid timestamp type {type(value).__name__} at index {entry_index} in {source_path}"
    )


def to_iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def to_iso_ny(dt: datetime) -> str:
    return dt.astimezone(_NY_TZ).isoformat()


def date_ny(dt: datetime) -> str:
    return dt.astimezone(_NY_TZ).date().isoformat()


def compact_json(value: Any) -> Optional[str]:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _format_float(value: float) -> str:
    return repr(float(value))


def _format_optional_float(value: Optional[float]) -> str:
    if value is None:
        return ""
    return _format_float(value)


# Hash recipe: SHA256 of the string
# venue|order_id|symbol|side|qty|price|ts_utc|source_path|raw_json(optional)
# Fields are concatenated with '|', price and raw_json are omitted if missing.

def build_fill_id(
    *,
    venue: str,
    order_id: str,
    symbol: str,
    side: str,
    qty: float,
    price: Optional[float],
    ts_utc: str,
    source_path: str,
    raw_json: Optional[str],
) -> str:
    parts = [
        venue,
        order_id,
        symbol,
        side,
        _format_float(qty),
        _format_optional_float(price),
        ts_utc,
        source_path,
    ]
    if raw_json is not None:
        parts.append(raw_json)
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def sort_fills(fills: Iterable[Any]) -> list[Any]:
    def _price_key(value: Optional[float]) -> tuple[bool, float]:
        if value is None:
            return (True, 0.0)
        return (False, float(value))

    return sorted(
        fills,
        key=lambda fill: (
            fill.ts_utc,
            fill.symbol,
            fill.side,
            fill.order_id,
            float(fill.qty),
            _price_key(fill.price),
            fill.fill_id,
        ),
    )
