"""State-file schema versioning helpers.

State files at ``state/strategies/{BOOK_ID}/{STRATEGY_ID}.json`` carry the
strategy's last-known regime, allocations, and trade-cooldown metadata.
Multiple writers touch them (raec_401k_base, raec_401k_coordinator,
schwab_seed_allocations); without a schema version key, a forward-incompat
change to one writer can silently corrupt readers.

This module provides:

* ``STATE_SCHEMA_VERSION`` — the version this code understands.
* ``stamp_schema_version(state)`` — guarantees the key is present.
* ``validate_schema_version(state, *, label)`` — raises if the file is
  written by a future version. Missing key is tolerated (legacy files
  default to v1).
"""

from __future__ import annotations

from typing import Any

STATE_SCHEMA_VERSION = 1


class StateSchemaError(Exception):
    """Raised when a state file is written by a schema version newer than this code."""


def stamp_schema_version(state: dict[str, Any]) -> dict[str, Any]:
    """Set ``state["schema_version"] = STATE_SCHEMA_VERSION`` and return ``state``.

    Idempotent. Always writes the current version, even if the state was
    loaded as a legacy v0 / pre-versioned file.
    """
    state["schema_version"] = STATE_SCHEMA_VERSION
    return state


def validate_schema_version(state: dict[str, Any], *, label: str) -> int:
    """Verify ``state`` was not written by a future schema version.

    Returns the version found (defaulting to ``STATE_SCHEMA_VERSION`` if the
    key is absent — legacy files predate versioning and are treated as v1).
    Raises ``StateSchemaError`` if the file's version exceeds what this code
    understands.
    """
    raw = state.get("schema_version", STATE_SCHEMA_VERSION)
    try:
        sv = int(raw)
    except (TypeError, ValueError):
        raise StateSchemaError(
            f"{label}: schema_version is non-integer ({raw!r})"
        )
    if sv > STATE_SCHEMA_VERSION:
        raise StateSchemaError(
            f"{label}: state file schema_version={sv} is newer than this "
            f"code ({STATE_SCHEMA_VERSION}); upgrade required before reading"
        )
    return sv
