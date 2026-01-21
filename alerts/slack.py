import os
import time
import threading
from datetime import datetime, time as dt_time
from zoneinfo import ZoneInfo
import json
import requests
from typing import Optional, Tuple, Iterable

# Levels (ordered)
_LEVELS = {"INFO": 10, "TRADE": 15, "WARNING": 20, "ERROR": 30}

# Simple in-memory throttling: key -> last_ts
_LAST_TS: dict[str, float] = {}
_LAST_DAILY_SUMMARY_DATE: Optional[str] = None
_LAST_MARKET_OPEN: Optional[bool] = None
_NY_TZ = ZoneInfo("America/New_York")


def _debug(msg: str) -> None:
    if os.getenv("SLACK_DEBUG", "0").strip() in ("1", "true", "TRUE", "yes", "YES"):
        print(f"[SLACK_DEBUG] {msg}", flush=True)


def _truthy(value: str) -> bool:
    return value.strip() in ("1", "true", "TRUE", "yes", "YES")


def _enabled() -> bool:
    url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    enabled_env = os.getenv("SLACK_ENABLED")
    if enabled_env is None:
        enabled_env = os.getenv("SLACK_ALERTS_ENABLED", "1")
    enabled = _truthy(enabled_env)
    if not enabled:
        _debug("SLACK_ENABLED is off; alerts disabled.")
        return False
    if not url:
        _debug("SLACK_WEBHOOK_URL is empty/missing; alerts disabled.")
        return False
    _debug(f"Slack alerts enabled (webhook present, len={len(url)}).")
    return True


def _min_level_ok(level: str) -> bool:
    min_level = os.getenv("SLACK_ALERTS_MIN_LEVEL", "INFO").strip().upper()
    return _LEVELS.get(level, 10) >= _LEVELS.get(min_level, 10)


def slack_verbose_enabled() -> bool:
    return _truthy(os.getenv("SLACK_VERBOSE", "0"))


def should_throttle(key: str, cooldown_seconds: int) -> bool:
    """Return True if a message for this key should be suppressed."""
    now = time.time()
    last = _LAST_TS.get(key, 0.0)
    if cooldown_seconds > 0 and (now - last) < cooldown_seconds:
        return True
    _LAST_TS[key] = now
    return False


def _post(payload: dict) -> None:
    url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not url:
        _debug("No SLACK_WEBHOOK_URL set; skipping post.")
        return
    try:
        # Hard timeouts so we never block systemd services
        resp = requests.post(url, json=payload, timeout=(2, 3))
        if resp.status_code != 200:
            _debug(f"Slack webhook HTTP {resp.status_code}: {resp.text[:200]}")
        else:
            _debug("Slack webhook POST ok.")
    except Exception as e:
        _debug(f"Slack webhook exception: {type(e).__name__}: {e}")


def slack_alert(
    level: str,
    title: str,
    message: str,
    component: str = "BOT",
    *,
    throttle_key: Optional[str] = None,
    throttle_seconds: int = 0,
) -> None:
    """
    Non-blocking Slack alert via Incoming Webhook.

    - No-ops if SLACK_WEBHOOK_URL missing or SLACK_ALERTS_ENABLED=0
    - Uses a short background thread and tight HTTP timeouts
    - Optional throttle to avoid alert storms
    """
    level = (level or "INFO").strip().upper()
    if level not in _LEVELS:
        level = "INFO"

    if not _enabled() or not _min_level_ok(level):
        return

    if throttle_key and should_throttle(throttle_key, throttle_seconds):
        return

    prefix = f"[AVWAP][{component}][{level}]"
    text = f"{prefix} {title}\n{message}".strip()

    payload: dict = {"text": text}

    # Optional overrides (webhook must allow)
    chan = os.getenv("SLACK_ALERTS_CHANNEL", "").strip()
    if chan:
        payload["channel"] = chan
    username = os.getenv("SLACK_ALERTS_USERNAME", "").strip()
    if username:
        payload["username"] = username

    def _worker() -> None:
        _post(payload)

    threading.Thread(target=_worker, daemon=True).start()


def send_verbose_alert(
    level: str,
    title: str,
    message: str,
    component: str = "BOT",
    *,
    throttle_key: Optional[str] = None,
    throttle_seconds: int = 0,
) -> None:
    if not slack_verbose_enabled():
        return
    slack_alert(
        level,
        title,
        message,
        component=component,
        throttle_key=throttle_key,
        throttle_seconds=throttle_seconds,
    )


def _now_ny() -> datetime:
    return datetime.now(tz=_NY_TZ)


def _today_ny_str() -> str:
    return _now_ny().date().isoformat()


def _watchlist_path_from_env() -> str:
    watchlist_file = os.getenv("WATCHLIST_FILE", "daily_candidates.csv").strip()
    if os.path.isabs(watchlist_file):
        return watchlist_file
    base_dir = os.getenv("AVWAP_BASE_DIR", "/root/avwap_r3k_scanner").strip()
    if not base_dir:
        base_dir = os.getcwd()
    return os.path.join(base_dir, watchlist_file)


def check_watchlist_freshness(watchlist_path: Optional[str] = None) -> Tuple[bool, str]:
    path = watchlist_path or _watchlist_path_from_env()
    if not os.path.exists(path):
        return False, f"missing ({path})"
    try:
        mtime = os.path.getmtime(path)
        file_date = datetime.fromtimestamp(mtime, tz=_NY_TZ).date().isoformat()
    except Exception as exc:
        return False, f"mtime error ({type(exc).__name__})"
    today = _today_ny_str()
    if file_date != today:
        return False, f"stale (file_date={file_date})"
    return True, f"fresh (file_date={file_date})"


def _format_top_qty(entries: Iterable[dict]) -> str:
    top = []
    for entry in entries:
        symbol = str(entry.get("symbol", "")).upper()
        qty = entry.get("qty")
        try:
            qty_int = int(qty)
        except Exception:
            qty_int = 0
        if symbol:
            top.append((symbol, qty_int))
    top = sorted(top, key=lambda item: item[1], reverse=True)[:5]
    if not top:
        return "Top qty: none"
    lines = ["Top qty (simulated submissions):"]
    for symbol, qty_int in top:
        lines.append(f"- {symbol}: {qty_int}")
    return "\n".join(lines)


def build_dry_run_daily_summary(ledger_path: str, date_ny: str) -> str:
    try:
        with open(ledger_path, "r") as f:
            ledger = json.load(f)
    except Exception:
        ledger = {}

    entries = []
    for key, value in ledger.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(f"{date_ny}:"):
            continue
        if isinstance(value, dict):
            entries.append(value)

    total = len(entries)
    symbols = {str(entry.get("symbol", "")).upper() for entry in entries if entry.get("symbol")}
    top_block = _format_top_qty(entries)
    lines = [
        f"Date (NY): {date_ny}",
        f"Total simulated submissions: {total}",
        f"Unique symbols: {len(symbols)}",
        top_block,
    ]
    return "\n".join(lines)


def maybe_send_heartbeat(
    *,
    dry_run: bool,
    market_open: bool,
    component: str = "EXECUTION_V2",
) -> None:
    minutes = int(os.getenv("SLACK_HEARTBEAT_MINUTES", "60"))
    if minutes <= 0:
        return
    status, detail = check_watchlist_freshness()
    mode = "DRY_RUN" if dry_run else "LIVE"
    market_status = "OPEN" if market_open else "CLOSED"
    freshness = "PASS" if status else "FAIL"
    message = (
        f"mode={mode}\n"
        f"market={market_status}\n"
        f"watchlist_freshness={freshness} ({detail})"
    )
    slack_alert(
        "INFO",
        "Execution heartbeat",
        message,
        component=component,
        throttle_key="slack_heartbeat",
        throttle_seconds=minutes * 60,
    )


def _parse_summary_time(value: str) -> Optional[dt_time]:
    if not value:
        return None
    try:
        parts = value.strip().split(":")
        if len(parts) != 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        return dt_time(hour=hour, minute=minute, tzinfo=_NY_TZ)
    except Exception:
        return None


def maybe_send_daily_summary(
    *,
    dry_run: bool,
    market_open: bool,
    component: str = "EXECUTION_V2",
) -> None:
    global _LAST_DAILY_SUMMARY_DATE
    global _LAST_MARKET_OPEN

    now_ny = _now_ny()
    today = now_ny.date().isoformat()
    summary_time = _parse_summary_time(os.getenv("SLACK_DAILY_SUMMARY_TIME", ""))
    trigger = False

    if summary_time is not None:
        if now_ny.timetz() >= summary_time and _LAST_DAILY_SUMMARY_DATE != today:
            trigger = True
    else:
        if _LAST_MARKET_OPEN is True and market_open is False and _LAST_DAILY_SUMMARY_DATE != today:
            trigger = True

    _LAST_MARKET_OPEN = market_open

    if not trigger:
        return

    if dry_run:
        ledger_path = os.getenv(
            "DRY_RUN_LEDGER_PATH",
            "/root/avwap_r3k_scanner/state/dry_run_ledger.json",
        )
        message = build_dry_run_daily_summary(ledger_path, today)
        title = "Daily execution summary (DRY_RUN)"
    else:
        message = "Date (NY): {date}\nLive summary unavailable (no persistent live ledger found).".format(
            date=today
        )
        title = "Daily execution summary (LIVE)"

    slack_alert("INFO", title, message, component=component)
    _LAST_DAILY_SUMMARY_DATE = today
