from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

REQUIRED_PROVENANCE_FIELDS = (
    "run_id",
    "git_sha",
    "config_hash",
    "data_hash",
    "data_path",
    "execution_mode",
    "parameters_used",
)

ALLOWED_EXECUTION_MODES = {"single", "sweep", "walk_forward"}


def ensure_local_path(path: Path) -> None:
    parsed = urlparse(str(path))
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"Only local filesystem paths are allowed: {path}")


def canonical_json(payload: dict) -> str:
    try:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except TypeError as exc:
        raise ValueError(f"Payload is not JSON-serializable: {exc}") from exc


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compute_data_hash(path: Path) -> str:
    ensure_local_path(path)
    with open(path, "rb") as handle:
        return _sha256_bytes(handle.read())


def compute_config_hash(cfg) -> str:
    keys = [
        "BACKTEST_ENTRY_MODEL",
        "BACKTEST_MAX_HOLD_DAYS",
        "BACKTEST_INITIAL_CASH",
        "BACKTEST_INITIAL_EQUITY",
        "BACKTEST_MIN_DOLLAR_POSITION",
        "BACKTEST_STRICT_SCHEMA",
        "BACKTEST_DEBUG_SAVE_CANDIDATES",
        "BACKTEST_VERBOSE",
        "BACKTEST_DYNAMIC_SCAN",
        "BACKTEST_STATIC_UNIVERSE",
        "BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS",
    ]
    subset = {key: getattr(cfg, key, None) for key in keys}
    return _sha256_bytes(canonical_json(subset).encode("utf-8"))


def compute_run_id(
    git_sha: str,
    config_hash: str,
    data_hash: str,
    execution_mode: str,
    parameters_used: dict,
) -> str:
    payload = {
        "git_sha": git_sha,
        "config_hash": config_hash,
        "data_hash": data_hash,
        "execution_mode": execution_mode,
        "parameters_used": parameters_used,
    }
    return _sha256_bytes(canonical_json(payload).encode("utf-8"))


def git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def require_provenance_fields(payload: dict, *, context: str) -> None:
    missing: list[str] = []
    for key in REQUIRED_PROVENANCE_FIELDS:
        if key not in payload:
            missing.append(key)
            continue
        value = payload[key]
        if value is None or value == "":
            missing.append(key)
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(f"Missing required provenance fields for {context}: {joined}")


def validate_execution_mode(mode: str) -> None:
    if mode not in ALLOWED_EXECUTION_MODES:
        allowed = ", ".join(sorted(ALLOWED_EXECUTION_MODES))
        raise ValueError(f"Unsupported execution_mode '{mode}'. Allowed: {allowed}")
