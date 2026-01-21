"""
Execution V2 – Live Trading Gate and Safety Controls
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

_NY_TZ = ZoneInfo("America/New_York")
_LAST_LIVE_ENABLED: Optional[bool] = None
_LAST_KILL_SWITCH_ACTIVE: Optional[bool] = None


def _truthy(value: str) -> bool:
    return value.strip() in ("1", "true", "TRUE", "yes", "YES")


def _state_dir(override: Optional[str] = None) -> str:
    if override:
        return override
    base = os.getenv("AVWAP_STATE_DIR", "/root/avwap_r3k_scanner/state").strip()
    if not base:
        return "/root/avwap_r3k_scanner/state"
    return base


def _today_ny_str() -> str:
    from datetime import datetime

    return datetime.now(tz=_NY_TZ).date().isoformat()


def _kill_switch_path(state_dir: Optional[str] = None) -> str:
    return os.path.join(_state_dir(state_dir), "KILL_SWITCH")


def _confirm_token_path(state_dir: Optional[str] = None) -> str:
    return os.path.join(_state_dir(state_dir), "live_confirm_token.txt")


def _ledger_path(state_dir: Optional[str] = None) -> str:
    return os.path.join(_state_dir(state_dir), "live_orders_today.json")


def is_kill_switch_active(state_dir: Optional[str] = None) -> Tuple[bool, str]:
    env_active = _truthy(os.getenv("KILL_SWITCH", "0"))
    file_path = _kill_switch_path(state_dir)
    file_active = os.path.exists(file_path)
    if env_active:
        return True, "env"
    if file_active:
        return True, "file"
    return False, "inactive"


def live_trading_enabled(state_dir: Optional[str] = None) -> Tuple[bool, str]:
    if not _truthy(os.getenv("LIVE_TRADING", "0")):
        return False, "LIVE_TRADING disabled"
    env_token = os.getenv("LIVE_CONFIRM_TOKEN", "").strip()
    if not env_token:
        return False, "LIVE_CONFIRM_TOKEN missing"
    token_path = _confirm_token_path(state_dir)
    try:
        with open(token_path, "r") as f:
            file_token = f.read().strip()
    except Exception:
        return False, "confirm token file missing"
    if not file_token:
        return False, "confirm token file empty"
    if env_token != file_token:
        return False, "LIVE_CONFIRM_TOKEN mismatch"
    return True, "live trading confirmed"


@dataclass(frozen=True)
class LiveModeResult:
    live_enabled: bool
    reason: str
    status: str
    mode: str
    kill_switch_active: bool


def resolve_live_mode(dry_run: bool, state_dir: Optional[str] = None) -> LiveModeResult:
    kill_switch_active, kill_reason = is_kill_switch_active(state_dir)
    if dry_run:
        return LiveModeResult(
            live_enabled=False,
            reason="DRY_RUN enabled",
            status="FAIL",
            mode="DRY_RUN",
            kill_switch_active=kill_switch_active,
        )
    if kill_switch_active:
        return LiveModeResult(
            live_enabled=False,
            reason=f"kill switch active ({kill_reason})",
            status="FAIL",
            mode="DRY_RUN",
            kill_switch_active=kill_switch_active,
        )
    enabled, reason = live_trading_enabled(state_dir)
    if not enabled:
        return LiveModeResult(
            live_enabled=False,
            reason=reason,
            status="FAIL",
            mode="DRY_RUN",
            kill_switch_active=kill_switch_active,
        )
    return LiveModeResult(
        live_enabled=True,
        reason=reason,
        status="PASS",
        mode="LIVE",
        kill_switch_active=kill_switch_active,
    )


def notify_live_status(live_enabled: bool) -> None:
    from alerts.slack import slack_alert

    global _LAST_LIVE_ENABLED
    if _LAST_LIVE_ENABLED is None:
        _LAST_LIVE_ENABLED = live_enabled
    if live_enabled and not _LAST_LIVE_ENABLED:
        slack_alert(
            "INFO",
            "Live trading enabled",
            "Live trading gate passed. Orders will be submitted live.",
            component="EXECUTION_V2",
            throttle_key="live_trading_enabled",
            throttle_seconds=300,
        )
    _LAST_LIVE_ENABLED = live_enabled


def notify_kill_switch(active: bool) -> None:
    from alerts.slack import slack_alert

    global _LAST_KILL_SWITCH_ACTIVE
    if _LAST_KILL_SWITCH_ACTIVE is None:
        _LAST_KILL_SWITCH_ACTIVE = active
    if active and not _LAST_KILL_SWITCH_ACTIVE:
        slack_alert(
            "WARNING",
            "Kill switch active",
            "Kill switch is active. Live orders are disabled.",
            component="EXECUTION_V2",
            throttle_key="kill_switch_active",
            throttle_seconds=300,
        )
    _LAST_KILL_SWITCH_ACTIVE = active


def parse_allowlist() -> Optional[set[str]]:
    raw = os.getenv("ALLOWLIST_SYMBOLS", "").strip()
    if not raw:
        return None
    symbols = {s.strip().upper() for s in raw.split(",") if s.strip()}
    return symbols or None


@dataclass(frozen=True)
class CapsConfig:
    max_orders_per_day: int
    max_positions: int
    max_gross_notional: float
    max_notional_per_symbol: float

    @classmethod
    def from_env(cls) -> "CapsConfig":
        return cls(
            max_orders_per_day=_int_env("MAX_LIVE_ORDERS_PER_DAY", 5),
            max_positions=_int_env("MAX_LIVE_POSITIONS", 5),
            max_gross_notional=_float_env("MAX_LIVE_GROSS_NOTIONAL", 5000.0),
            max_notional_per_symbol=_float_env("MAX_LIVE_NOTIONAL_PER_SYMBOL", 1000.0),
        )

    def summary(self) -> str:
        return (
            "caps"
            f"(orders/day={self.max_orders_per_day}, "
            f"positions={self.max_positions}, "
            f"gross_notional={self.max_gross_notional}, "
            f"per_symbol={self.max_notional_per_symbol})"
        )


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except Exception:
        return default


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except Exception:
        return default


def allowlist_summary(allowlist: Optional[set[str]]) -> str:
    if not allowlist:
        return "allowlist=ALL"
    return f"allowlist={','.join(sorted(allowlist))}"


class LiveLedgerError(RuntimeError):
    pass


class LiveLedger:
    def __init__(self, path: str, date_ny: str, entries: list[dict], *, was_reset: bool = False) -> None:
        self.path = path
        self.date_ny = date_ny
        self.entries = entries
        self.was_reset = was_reset

    @classmethod
    def load(cls, path: str, today_ny: str) -> "LiveLedger":
        if not os.path.exists(path):
            raise LiveLedgerError("ledger missing")
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception as exc:
            raise LiveLedgerError(f"ledger unreadable ({type(exc).__name__})") from exc
        if not isinstance(data, dict):
            raise LiveLedgerError("ledger invalid")
        date_ny = data.get("date_ny")
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            raise LiveLedgerError("ledger invalid entries")
        if date_ny != today_ny:
            return cls(path, today_ny, [], was_reset=True)
        return cls(path, today_ny, entries, was_reset=False)

    @classmethod
    def initialize(cls, path: str, today_ny: str) -> "LiveLedger":
        return cls(path, today_ny, [], was_reset=True)

    def count_orders(self) -> int:
        return len(self.entries)

    def gross_notional(self) -> float:
        total = 0.0
        for entry in self.entries:
            try:
                total += float(entry.get("notional", 0.0))
            except Exception:
                continue
        return total

    def notional_for_symbol(self, symbol: str) -> float:
        total = 0.0
        sym = symbol.upper()
        for entry in self.entries:
            if str(entry.get("symbol", "")).upper() != sym:
                continue
            try:
                total += float(entry.get("notional", 0.0))
            except Exception:
                continue
        return total

    def add_entry(self, order_id: str, symbol: str, notional: float, ts: str) -> None:
        self.entries.append(
            {
                "order_id": order_id,
                "symbol": symbol.upper(),
                "notional": float(notional),
                "timestamp": ts,
            }
        )

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        payload = {"date_ny": self.date_ny, "entries": self.entries}
        with open(self.path, "w") as f:
            json.dump(payload, f)


def load_live_ledger(state_dir: Optional[str] = None) -> Tuple[Optional[LiveLedger], str]:
    today_ny = _today_ny_str()
    path = _ledger_path(state_dir)
    try:
        ledger = LiveLedger.load(path, today_ny)
    except LiveLedgerError as exc:
        if "ledger missing" in str(exc):
            try:
                LiveLedger.initialize(path, today_ny).save()
            except Exception:
                pass
        return None, str(exc)
    return ledger, "ok"


def enforce_caps(
    intent,
    ledger: LiveLedger,
    allowlist: Optional[set[str]],
    caps: CapsConfig,
    *,
    open_positions: Optional[int],
) -> Tuple[bool, str]:
    symbol = str(getattr(intent, "symbol", "")).upper().strip()
    if not symbol:
        return False, "symbol missing"
    if allowlist and symbol not in allowlist:
        return False, "allowlist blocked"
    if open_positions is None:
        return False, "positions unknown"
    if caps.max_positions <= 0 or caps.max_orders_per_day <= 0:
        return False, "invalid cap configuration"
    if open_positions >= caps.max_positions:
        return False, "max positions reached"
    try:
        qty = int(getattr(intent, "size_shares", 0))
        price = float(getattr(intent, "ref_price", 0.0))
        notional = float(qty) * float(price)
    except Exception:
        return False, "notional unavailable"
    if qty <= 0 or price <= 0 or notional <= 0:
        return False, "notional invalid"
    if ledger.count_orders() + 1 > caps.max_orders_per_day:
        return False, "max orders/day reached"
    if caps.max_gross_notional <= 0 or caps.max_notional_per_symbol <= 0:
        return False, "invalid notional caps"
    if ledger.gross_notional() + notional > caps.max_gross_notional:
        return False, "max gross notional reached"
    if ledger.notional_for_symbol(symbol) + notional > caps.max_notional_per_symbol:
        return False, "max symbol notional reached"
    return True, "caps ok"
