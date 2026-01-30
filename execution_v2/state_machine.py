"""
Execution V2 – Symbol execution state machine (JSON persisted).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Iterable

from utils.atomic_write import atomic_write_text

DEFAULT_STATE_DIR = "/root/avwap_r3k_scanner/state"


@dataclass
class SymbolExecutionState:
    state: str = "FLAT"
    last_transition_ts_utc: str | None = None
    entry_intent_id: str | None = None
    entry_order_ids: list[str] = field(default_factory=list)
    exit_order_ids: list[str] = field(default_factory=list)
    entry_fill_ts_utc: str | None = None
    last_exit_ts_utc: str | None = None

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "last_transition_ts_utc": self.last_transition_ts_utc,
            "entry_intent_id": self.entry_intent_id,
            "entry_order_ids": list(self.entry_order_ids),
            "exit_order_ids": list(self.exit_order_ids),
            "entry_fill_ts_utc": self.entry_fill_ts_utc,
            "last_exit_ts_utc": self.last_exit_ts_utc,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "SymbolExecutionState":
        return cls(
            state=str(payload.get("state", "FLAT")),
            last_transition_ts_utc=payload.get("last_transition_ts_utc"),
            entry_intent_id=payload.get("entry_intent_id"),
            entry_order_ids=list(payload.get("entry_order_ids") or []),
            exit_order_ids=list(payload.get("exit_order_ids") or []),
            entry_fill_ts_utc=payload.get("entry_fill_ts_utc"),
            last_exit_ts_utc=payload.get("last_exit_ts_utc"),
        )


@dataclass
class SymbolExecutionSnapshot:
    date_ny: str
    updated_ts_utc: str | None
    symbols: dict[str, SymbolExecutionState]

    def to_dict(self) -> dict:
        return {
            "date_ny": self.date_ny,
            "updated_ts_utc": self.updated_ts_utc,
            "symbols": {sym: state.to_dict() for sym, state in self.symbols.items()},
        }

    @classmethod
    def empty(cls, date_ny: str) -> "SymbolExecutionSnapshot":
        return cls(date_ny=date_ny, updated_ts_utc=None, symbols={})

    @classmethod
    def from_dict(cls, payload: dict, date_ny: str) -> "SymbolExecutionSnapshot":
        raw_symbols = payload.get("symbols") or {}
        symbols = {
            str(sym).upper(): SymbolExecutionState.from_dict(state)
            for sym, state in raw_symbols.items()
        }
        updated_ts_utc = payload.get("updated_ts_utc")
        return cls(date_ny=date_ny, updated_ts_utc=updated_ts_utc, symbols=symbols)


class SymbolExecutionStateStore:
    def __init__(self, date_ny: str, state_dir: Path | None = None) -> None:
        self.date_ny = date_ny
        self.state_dir = state_dir or _state_dir()
        self.path = self.state_dir / f"symbol_execution_state_{date_ny}.json"
        self.snapshot = SymbolExecutionSnapshot.empty(date_ny)
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._loaded = True
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._loaded = True
            return
        self.snapshot = SymbolExecutionSnapshot.from_dict(payload, self.date_ny)
        self._loaded = True

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        now_utc = datetime.now(timezone.utc).isoformat()
        self.snapshot.updated_ts_utc = now_utc
        payload = json.dumps(self.snapshot.to_dict(), sort_keys=True)
        atomic_write_text(self.path, payload)

    def get(self, symbol: str) -> SymbolExecutionState:
        self.load()
        key = str(symbol or "").upper()
        state = self.snapshot.symbols.get(key)
        if state is None:
            state = SymbolExecutionState()
            self.snapshot.symbols[key] = state
        return state

    def update(self, symbol: str, state: SymbolExecutionState) -> None:
        self.load()
        key = str(symbol or "").upper()
        self.snapshot.symbols[key] = state

    def transition(
        self,
        symbol: str,
        new_state: str,
        *,
        now_utc: datetime,
        entry_intent_id: str | None = None,
        entry_order_id: str | None = None,
        exit_order_id: str | None = None,
        entry_fill_ts_utc: str | None = None,
        last_exit_ts_utc: str | None = None,
    ) -> None:
        state = self.get(symbol)
        state.state = new_state
        state.last_transition_ts_utc = now_utc.isoformat()
        if entry_intent_id is not None:
            state.entry_intent_id = entry_intent_id
        if entry_order_id is not None:
            if entry_order_id not in state.entry_order_ids:
                state.entry_order_ids.append(entry_order_id)
        if exit_order_id is not None:
            if exit_order_id not in state.exit_order_ids:
                state.exit_order_ids.append(exit_order_id)
        if entry_fill_ts_utc is not None:
            state.entry_fill_ts_utc = entry_fill_ts_utc
        if last_exit_ts_utc is not None:
            state.last_exit_ts_utc = last_exit_ts_utc
        self.update(symbol, state)

    def apply_open_positions(
        self,
        symbols_open: Iterable[str],
        *,
        now_utc: datetime,
        entry_fill_ts_utc: dict[str, str] | None = None,
    ) -> None:
        self.load()
        open_set = {str(sym).upper() for sym in symbols_open if sym}
        for symbol in sorted(open_set):
            state = self.get(symbol)
            if state.state in {"FLAT", "ENTERING"}:
                fill_ts = None
                if entry_fill_ts_utc:
                    fill_ts = entry_fill_ts_utc.get(symbol)
                if fill_ts is None:
                    fill_ts = now_utc.isoformat()
                self.transition(
                    symbol,
                    "OPEN",
                    now_utc=now_utc,
                    entry_fill_ts_utc=fill_ts,
                )
        for symbol, state in list(self.snapshot.symbols.items()):
            if symbol in open_set:
                continue
            if state.state == "EXITING":
                self.transition(
                    symbol,
                    "FLAT",
                    now_utc=now_utc,
                    last_exit_ts_utc=now_utc.isoformat(),
                )


@dataclass
class ConsumedEntries:
    date_ny: str
    updated_ts_utc: str | None
    consumed: set[str]

    def to_dict(self) -> dict:
        return {
            "date_ny": self.date_ny,
            "updated_ts_utc": self.updated_ts_utc,
            "consumed": sorted(self.consumed),
        }


class ConsumedEntriesStore:
    def __init__(self, date_ny: str, state_dir: Path | None = None) -> None:
        self.date_ny = date_ny
        self.state_dir = state_dir or _state_dir()
        self.path = self.state_dir / f"consumed_entries_{date_ny}.json"
        self._consumed = ConsumedEntries(date_ny=date_ny, updated_ts_utc=None, consumed=set())
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._loaded = True
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._loaded = True
            return
        consumed = payload.get("consumed") or []
        self._consumed = ConsumedEntries(
            date_ny=self.date_ny,
            updated_ts_utc=payload.get("updated_ts_utc"),
            consumed={str(sym).upper() for sym in consumed},
        )
        self._loaded = True

    def save(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        now_utc = datetime.now(timezone.utc).isoformat()
        self._consumed.updated_ts_utc = now_utc
        payload = json.dumps(self._consumed.to_dict(), sort_keys=True)
        atomic_write_text(self.path, payload)

    def is_consumed(self, symbol: str) -> bool:
        self.load()
        return str(symbol or "").upper() in self._consumed.consumed

    def mark(self, symbol: str, now_utc: datetime) -> None:
        self.load()
        self._consumed.consumed.add(str(symbol or "").upper())
        self._consumed.updated_ts_utc = now_utc.isoformat()
        self.save()


def _state_dir() -> Path:
    base = os.getenv("AVWAP_STATE_DIR", DEFAULT_STATE_DIR).strip()
    if not base:
        base = DEFAULT_STATE_DIR
    return Path(base)


def resolve_entry_fill_ts_utc(entry_fill_record) -> str | None:
    if entry_fill_record is None:
        return None
    try:
        filled_ts = float(entry_fill_record["filled_ts"])
    except Exception:
        return None
    return datetime.fromtimestamp(filled_ts, tz=timezone.utc).isoformat()


def is_exit_armed(
    *,
    entry_fill_ts_utc: str | None,
    now_utc: datetime,
    min_seconds: int,
    closed_10m_bars: list | None = None,
) -> bool:
    if entry_fill_ts_utc is None:
        return False
    try:
        entry_ts = datetime.fromisoformat(entry_fill_ts_utc)
    except Exception:
        return False
    if closed_10m_bars:
        try:
            last_bar = closed_10m_bars[-1]
            last_ts = getattr(last_bar, "ts", None)
            if last_ts is None:
                last_ts = last_bar.get("ts") if isinstance(last_bar, dict) else None
            if last_ts is not None:
                if float(last_ts) - entry_ts.timestamp() >= 600:
                    return True
        except Exception:
            pass
    return (now_utc - entry_ts).total_seconds() >= max(min_seconds, 0)
