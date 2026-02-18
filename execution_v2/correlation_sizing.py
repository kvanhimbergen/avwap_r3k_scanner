"""Correlation-aware sizing: penalty function and sector cap enforcement (Phase 5)."""

from __future__ import annotations

import pandas as pd


def correlation_penalty(
    candidate_symbol: str,
    open_positions: list[str],
    corr_matrix: pd.DataFrame,
    threshold: float = 0.6,
    max_penalty: float = 0.5,
) -> float:
    """Returns penalty in [0, max_penalty]. Higher correlation => smaller size.

    Parameters
    ----------
    candidate_symbol : str
        Symbol being evaluated for entry.
    open_positions : list[str]
        Symbols currently held.
    corr_matrix : pd.DataFrame
        Pairwise correlation matrix (symmetric, symbols as index/columns).
    threshold : float
        Correlations below this are ignored.
    max_penalty : float
        Maximum penalty value.

    Returns
    -------
    float in [0.0, max_penalty].
    """
    if not open_positions or candidate_symbol not in corr_matrix.index:
        return 0.0

    corrs = [
        abs(corr_matrix.loc[candidate_symbol, pos])
        for pos in open_positions
        if pos in corr_matrix.columns
    ]
    if not corrs:
        return 0.0

    avg_corr = sum(corrs) / len(corrs)
    if avg_corr <= threshold:
        return 0.0

    excess = (avg_corr - threshold) / (1.0 - threshold)
    return min(excess * max_penalty, max_penalty)


def check_sector_cap(
    candidate_sector: str | None,
    open_positions: list[dict],
    sector_map: dict[str, str],
    max_sector_pct: float = 0.3,
    gross_exposure: float | None = None,
) -> tuple[bool, str]:
    """Check whether adding a candidate would breach sector concentration cap.

    Parameters
    ----------
    candidate_sector : str | None
        Sector of the candidate symbol.
    open_positions : list[dict]
        Each dict must have ``symbol`` and ``notional`` keys.
    sector_map : dict[str, str]
        Mapping of symbol -> sector.
    max_sector_pct : float
        Maximum fraction of gross exposure allowed in a single sector.
    gross_exposure : float | None
        Current total gross exposure. If None, computed from open_positions.

    Returns
    -------
    (allowed, reason) – allowed is True if the entry is permitted.
    """
    if not candidate_sector:
        return True, ""

    if gross_exposure is None:
        gross_exposure = sum(abs(float(p.get("notional", 0.0))) for p in open_positions)

    if gross_exposure <= 0:
        return True, ""

    sector_notional = 0.0
    for p in open_positions:
        sym = str(p.get("symbol", "")).upper()
        if sector_map.get(sym, "") == candidate_sector:
            sector_notional += abs(float(p.get("notional", 0.0)))

    # Estimate new candidate adds average-sized position
    avg_position = gross_exposure / max(len(open_positions), 1)
    projected_sector = sector_notional + avg_position
    projected_gross = gross_exposure + avg_position
    projected_pct = projected_sector / projected_gross

    if projected_pct > max_sector_pct:
        pct_display = round(projected_pct * 100, 1)
        return False, f"sector cap exceeded: {candidate_sector} at {pct_display}%"

    return True, ""
