"""Frozen dataclass schemas for feature store feature types."""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class TrendFeatures:
    """Per-symbol trend metrics computed during daily scan."""

    SCHEMA_VERSION: int = 1

    symbol: str = ""
    trend_score: float = 0.0
    sma50_slope: float = 0.0
    adx: float = 0.0
    vol_ratio: float = 0.0
    atr_pct: float = 0.0

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "SCHEMA_VERSION"}

    @classmethod
    def from_dict(cls, d: dict) -> TrendFeatures:
        valid = {f.name for f in fields(cls)} - {"SCHEMA_VERSION"}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass(frozen=True)
class RegimeFeatures:
    """Market-wide regime metrics (one row per date)."""

    SCHEMA_VERSION: int = 1

    spy_vol: float = 0.0
    spy_drawdown: float = 0.0
    spy_trend: float = 0.0
    breadth: float = 0.0
    regime_label: str = ""

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "SCHEMA_VERSION"}

    @classmethod
    def from_dict(cls, d: dict) -> RegimeFeatures:
        valid = {f.name for f in fields(cls)} - {"SCHEMA_VERSION"}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass(frozen=True)
class AVWAPFeatures:
    """Per-symbol AVWAP state features."""

    SCHEMA_VERSION: int = 1

    symbol: str = ""
    anchor: str = ""
    avwap_slope: float = 0.0
    dist_pct: float = 0.0
    setup_vwap_control: str = ""
    setup_avwap_control: str = ""
    setup_extension_state: str = ""
    setup_structure_state: str = ""

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "SCHEMA_VERSION"}

    @classmethod
    def from_dict(cls, d: dict) -> AVWAPFeatures:
        valid = {f.name for f in fields(cls)} - {"SCHEMA_VERSION"}
        return cls(**{k: v for k, v in d.items() if k in valid})


@dataclass(frozen=True)
class RegimeE2Features:
    """E2 multi-factor regime metrics (one row per date)."""

    SCHEMA_VERSION: int = 1

    spy_vol: float = 0.0
    spy_drawdown: float = 0.0
    spy_trend: float = 0.0
    breadth: float = 0.0
    credit_spread_z: float = 0.0
    vix_term_structure: float = 0.0
    gld_relative_strength: float = 0.0
    tlt_relative_strength: float = 0.0
    regime_label: str = ""
    regime_score: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self) if f.name != "SCHEMA_VERSION"}

    @classmethod
    def from_dict(cls, d: dict) -> RegimeE2Features:
        valid = {f.name for f in fields(cls)} - {"SCHEMA_VERSION"}
        return cls(**{k: v for k, v in d.items() if k in valid})


FEATURE_SCHEMAS: dict[str, type] = {
    "trend_features": TrendFeatures,
    "regime_features": RegimeFeatures,
    "avwap_features": AVWAPFeatures,
    "regime_e2_features": RegimeE2Features,
}


def schema_version_for(feature_type: str) -> int:
    cls = FEATURE_SCHEMAS.get(feature_type)
    if cls is None:
        raise ValueError(f"Unknown feature type: {feature_type}")
    return cls.SCHEMA_VERSION
