from dataclasses import dataclass, field
import os
from typing import Optional


def _parse_env_bool(value: str) -> Optional[bool]:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None

@dataclass
class CFG:
    # Universe source
    IWV_PRODUCT_ID: str = "239714"
    IWV_TICKER: str = "IWV"
    IWV_SLUG: str = "ishares-russell-3000-etf"

    # Baseline index
    INDEX: str = "SPY"

    # Scan windows
    HISTORY_PERIOD_FULL: str = "2y"          # used for first-time cache build
    HISTORY_PERIOD_LIQ: str = "2mo"          # weekly liquidity snapshot
    HISTORY_PERIOD_DAILY_UPDATE: str = "10d" # daily refresh window

    # Liquidity filters
    MIN_AVG_DOLLAR_VOL: float = 10_000_000
    MIN_PRICE: float = 3.0

    # Prefilter controls
    TOP_SECTORS_TO_SCAN: int = 11
    TOP_PER_SECTOR_BY_LIQ: int = 250
    SNAPSHOT_MAX_TICKERS: int = 3000

    # AVWAP / Trend
    ANCHOR_LOOKBACK: int = 60
    SWING_LOOKBACK: int = 20
    GAP_PCT: float = 0.04
    VOL_SPIKE_MULT: float = 1.8
    MAX_DIST_FROM_AVWAP_PCT: float = 6.0
    TREND_SCORE_MIN_LONG: float = 5.0
    TREND_SCORE_MIN_SHORT: float = -5.0
    TREND_SCORE_WARMUP: int = 120

    # Output caps
    CANDIDATE_CAP: int = 200

    # Controls
    ALLOW_SHORTS: bool = True
    SHORTS_ONLY_IN_RISK_OFF: bool = True

    # yfinance stability
    YF_BATCH_SIZE: int = 25
    YF_SLEEP_S: float = 1.2
    YF_RETRIES: int = 2
    YF_THREADS: bool = False

    # Cache behavior
    SNAPSHOT_MAX_AGE_DAYS: int = 7
    HISTORY_MAX_AGE_DAYS: int = 7

    # Universe sourcing controls
    UNIVERSE_ALLOW_NETWORK: bool = True
    BACKTEST_UNIVERSE_ALLOW_NETWORK: bool = False

    # Use the committed snapshot as the default offline universe source
    UNIVERSE_SNAPSHOT_PATH: str = "universe/snapshots/iwv_holdings_latest.csv"

    # Optional future enhancement location
    UNIVERSE_SNAPSHOT_DIR: str = "universe/snapshots"

    # Scan time control (None => live scan uses now)
    SCAN_AS_OF_DT: str | None = None

    # --- Setup: Pullback-in-Uptrend (daily bars) ---
    PULLBACK_TREND_ENABLED: bool = True

    PBT_SMA_FAST: int = 50
    PBT_SMA_SLOW: int = 200
    PBT_EMA_PULLBACK: int = 20
    PBT_EMA_TRIGGER: int = 9

    PBT_RSI_LEN: int = 14
    PBT_RSI_MIN: float = 40.0
    PBT_RSI_MAX: float = 65.0

    PBT_ATR_LEN: int = 14
    PBT_ATR_CONTRACT_LOOKBACK: int = 5  # ATR today < ATR N bars ago

    PBT_PULLBACK_LOOKBACK: int = 7  # touched EMA20 at least once in last N bars
    PBT_FORBID_CLOSE_BELOW_SMA_FAST_LOOKBACK: int = 2  # no closes below SMA50 in last N bars

    PBT_REQUIRE_ADX: bool = False
    PBT_ADX_LEN: int = 14
    PBT_ADX_MIN: float = 20.0

    PBT_REQUIRE_RS: bool = False
    PBT_RS_LOOKBACK: int = 15

    PBT_REQUIRE_TRIGGER: bool = True

    # Keep the final effective value from your existing file
    PBT_REQUIRE_ATR_CONTRACTION: bool = True

    WEEKEND_MODE: bool = True

    PBT_EMA20_PROX_PCT: float = 3.0  # within 1% of EMA20 counts as a pullback

    PBT_REQUIRE_SMA200_SLOPE: bool = False   # turn off the strictest part first
    PBT_SMA200_SLOPE_LOOKBACK: int = 40
    PBT_MIN_PCT_ABOVE_SMA200: float = 0.0   # optional buffer; start at 0.0

    PBT_TREND_SMA: int = 150

    # Trend regime tolerances
    PBT_MAX_PCT_BELOW_TREND_FOR_PRICE: float = 2.0
    PBT_MAX_PCT_BELOW_TREND_FOR_SMA50: float = 2.0

    # Allow "early transition" trend mode (price above SMA50 and SMA50 rising)
    PBT_ALLOW_EARLY_TRANSITION: bool = True
    PBT_SMA50_SLOPE_LOOKBACK: int = 10

    PBT_MAX_PCT_BELOW_SM50: float = 0.5

    PBT_RSI_NO_NEW_HIGH_LOOKBACK: int = 5

    # AVWAP slope gating (single source of truth)
    MIN_AVWAP_SLOPE_LONG: float = -0.03
    MIN_AVWAP_SLOPE_SHORT: float = 0.03
    AVWAP_SLOPE_LOOKBACK: int = 5
    AVWAP_SLOPE_BYPASS_ON_RECLAIM: bool = True

    # Alpaca Data Settings
    USE_PAPER_DATA: bool = True
    DATA_FEED: str = "sip"  # Use 'iex' if on free tier, 'sip' if on paid tier

    # Backtest configuration
    BACKTEST_AUTO_ADJUST: bool = True
    BACKTEST_ENTRY_MODEL: str = "next_open"
    BACKTEST_MAX_HOLD_DAYS: int = 5
    BACKTEST_INITIAL_CASH: float = 100_000.0
    BACKTEST_INITIAL_EQUITY: float = 100_000.0
    BACKTEST_RISK_PCT: float = 0.01
    BACKTEST_RISK_PER_TRADE_PCT: float = 0.01
    BACKTEST_MAX_CONCURRENT: int = 5
    BACKTEST_MAX_POSITIONS: int = 10
    BACKTEST_MAX_GROSS_EXPOSURE_PCT: float = 1.00
    BACKTEST_MAX_GROSS_EXPOSURE_DOLLARS: float = 1_000_000.0
    BACKTEST_MAX_RISK_PER_TRADE_DOLLARS: float = 1_000_000.0
    BACKTEST_MAX_NEW_ENTRIES_PER_DAY: int = 10_000
    BACKTEST_MAX_UNIQUE_SYMBOLS_PER_DAY: int = 10_000
    BACKTEST_KILL_SWITCH: bool = False
    BACKTEST_KILL_SWITCH_START_DATE: str | None = None
    BACKTEST_MIN_DOLLAR_POSITION: float = 1000.0
    BACKTEST_SLIPPAGE_BPS: float = 2.5
    BACKTEST_ENTRY_LIMIT_BPS: float = 10.0
    BACKTEST_EXTENSION_THRESH: float = 0.03
    BACKTEST_INVALIDATION_STOP_BUFFER_PCT: float = 0.002
    BACKTEST_COMMISSION_PER_TRADE: float = 1.0
    BACKTEST_BOOTSTRAP_SAMPLES: int = 1000
    BACKTEST_WINDOW_MONTHS: int = 12
    BACKTEST_WINDOW_STEP_MONTHS: int = 3
    BACKTEST_TICKER_SOURCE: str = "manual"  # manual | screen | universe
    BACKTEST_TICKER_LIMIT: int = 250
    BACKTEST_CANDIDATES_PATH: str = "daily_candidates.csv"
    BACKTEST_BENCHMARK_SYMBOL: str = "SPY"

    # Backtest controls
    BACKTEST_DYNAMIC_SCAN: bool = True
    BACKTEST_STATIC_UNIVERSE: bool = True
    BACKTEST_USE_DATED_UNIVERSE_SNAPSHOTS: bool = False
    BACKTEST_START_DATE: str | None = None
    BACKTEST_END_DATE: str | None = None
    BACKTEST_OHLCV_PATH: str = "cache/ohlcv_history.parquet"
    BACKTEST_OUTPUT_DIR: str = "backtests"
    BACKTEST_DEBUG_SAVE_CANDIDATES: bool = False
    BACKTEST_VERBOSE: bool = False
    BACKTEST_STRICT_SCHEMA: bool = False

    # Determinism
    BACKTEST_RANDOM_SEED: int = 42

    # Slippage measurement (Phase 1 – observational only)
    SLIPPAGE_LEDGER_ENABLED: bool = True
    SLIPPAGE_LIQUIDITY_BUCKETS: dict = field(default_factory=lambda: {
        "mega": 5_000_000,
        "large": 2_000_000,
        "mid": 750_000,
    })

    # Feature store (Phase 2)
    FEATURE_STORE_DIR: str = "feature_store"
    FEATURE_STORE_WRITE_ENABLED: bool = False
    FEATURE_STORE_SCHEMA_VERSION: int = 1

    # Backtest validation mode
    BACKTEST_VALIDATION_MODE: str = "rolling"
    BACKTEST_CPCV_N_GROUPS: int = 5
    BACKTEST_CPCV_K_SPLITS: int = 2
    BACKTEST_PURGE_DAYS: int = 5
    BACKTEST_EMBARGO_DAYS: int = 3
    BACKTEST_USE_FEATURE_STORE: bool = False

    def effective_universe_allow_network(self) -> bool:
        raw = os.getenv("UNIVERSE_ALLOW_NETWORK")
        if raw is None:
            return self.UNIVERSE_ALLOW_NETWORK
        parsed = _parse_env_bool(raw)
        if parsed is None:
            import logging

            logging.getLogger(__name__).warning(
                "Invalid UNIVERSE_ALLOW_NETWORK value %r; using config default %s",
                raw,
                self.UNIVERSE_ALLOW_NETWORK,
            )
            return self.UNIVERSE_ALLOW_NETWORK
        return parsed

    def get_universe_metrics(self, tickers: list[str]) -> dict[str, dict]:
        """
        Minimal universe metrics provider for universe.py.

        Returns:
            {
              "AAPL": {"last_price": float, "avg_vol_20d": float},
              ...
            }

        Uses yfinance and fails open per symbol.
        """
        import logging
        import re

        if not self.effective_universe_allow_network():
            raise RuntimeError(
                "Universe metrics requested but network access is disallowed (UNIVERSE_ALLOW_NETWORK=0)."
            )

        import yfinance as yf

        # Reduce yfinance noise
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)

        out: dict[str, dict] = {}
        if not tickers:
            return out

        # Filter out obvious non-Yahoo equity symbols (futures, odd lots, etc.)
        # Keep standard US tickers: letters, dot-class shares, hyphen.
        cleaned = []
        pat = re.compile(r"^[A-Z]{1,5}([.-][A-Z]{1,2})?$")
        for t in tickers:
            t = str(t).upper().strip()
            if pat.match(t):
                cleaned.append(t)

        if not cleaned:
            return out

        try:
            data = yf.download(
                tickers=cleaned,
                period="1mo",
                interval="1d",
                group_by="ticker",
                auto_adjust=False,
                threads=self.YF_THREADS,
                progress=False,
            )
        except Exception:
            return out

        for sym in cleaned:
            try:
                df = data[sym] if len(cleaned) > 1 else data
                if df is None or df.empty:
                    continue

                closes = df["Close"].dropna()
                vols = df["Volume"].dropna()
                if closes.empty or vols.empty:
                    continue

                out[sym] = {
                    "last_price": float(closes.iloc[-1]),
                    "avg_vol_20d": float(vols.tail(20).mean()),
                }
            except Exception:
                continue

        return out

    

cfg = CFG()
