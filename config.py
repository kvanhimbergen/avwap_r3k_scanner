from dataclasses import dataclass

@dataclass
class CFG:
    # Universe source
    IWV_PRODUCT_ID: str = "239714"
    IWV_TICKER: str = "IWV"
    IWV_SLUG: str = "ishares-russell-3000-etf"

    # Baseline index
    INDEX: str = "SPY"

    # Scan windows
    HISTORY_PERIOD_FULL: str = "2y"     # used for first-time cache build
    HISTORY_PERIOD_LIQ: str = "2mo"      # weekly liquidity snapshot
    HISTORY_PERIOD_DAILY_UPDATE: str = "10d"  # daily refresh window

    # Liquidity filters
    MIN_AVG_DOLLAR_VOL: float = 10_000_000
    MIN_PRICE: float = 3.0

    # Prefilter controls
    TOP_SECTORS_TO_SCAN: int = 11
    TOP_PER_SECTOR_BY_LIQ: int = 250
    SNAPSHOT_MAX_TICKERS: int = 3000

    # AVWAP / RS
    ANCHOR_LOOKBACK: int = 60
    SWING_LOOKBACK: int = 20
    RS_LOOKBACK: int = 20
    GAP_PCT: float = 0.04
    VOL_SPIKE_MULT: float = 1.8
    MAX_DIST_FROM_AVWAP_PCT: float = 6.0

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

    PBT_REQUIRE_ATR_CONTRACTION: bool = False

    WEEKEND_MODE: bool = True

    PBT_REQUIRE_ATR_CONTRACTION: bool = True

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

    MIN_AVWAP_SLOPE_LONG = -0.03
    AVWAP_SLOPE_LOOKBACK = 5
    AVWAP_SLOPE_BYPASS_ON_RECLAIM = True









cfg = CFG()


