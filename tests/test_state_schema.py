from __future__ import annotations

import pytest

from utils.state_schema import (
    STATE_SCHEMA_VERSION,
    StateSchemaError,
    stamp_schema_version,
    validate_schema_version,
)


def test_stamp_sets_current_version_on_empty_state() -> None:
    state: dict = {}
    stamp_schema_version(state)
    assert state["schema_version"] == STATE_SCHEMA_VERSION


def test_stamp_overwrites_existing_value() -> None:
    state = {"schema_version": 0}
    stamp_schema_version(state)
    assert state["schema_version"] == STATE_SCHEMA_VERSION


def test_validate_accepts_current_version() -> None:
    sv = validate_schema_version({"schema_version": STATE_SCHEMA_VERSION}, label="x")
    assert sv == STATE_SCHEMA_VERSION


def test_validate_accepts_legacy_state_without_key() -> None:
    # Pre-versioned state files default to v1 — legacy reads must not break.
    sv = validate_schema_version({"some": "data"}, label="legacy")
    assert sv == STATE_SCHEMA_VERSION


def test_validate_rejects_future_version() -> None:
    future = STATE_SCHEMA_VERSION + 1
    with pytest.raises(StateSchemaError, match=f"schema_version={future}"):
        validate_schema_version({"schema_version": future}, label="future_state")


def test_validate_rejects_non_integer_value() -> None:
    with pytest.raises(StateSchemaError, match="non-integer"):
        validate_schema_version({"schema_version": "not-a-number"}, label="bad_state")
