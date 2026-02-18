export interface ApiEnvelope<T> {
  as_of_utc: string;
  source_window: {
    date_min: string | null;
    date_max: string | null;
    [key: string]: unknown;
  };
  data_version: string;
  warnings: string[];
  data: T;
}

export interface KeyValue {
  [key: string]: unknown;
}

export interface TimePoint {
  ny_date: string;
  cycle_count: number;
  intent_count: number;
  created_count: number;
  accepted_count: number;
  rejected_count: number;
  gate_blocks: number;
}

export interface FreshnessRow {
  source_name: string;
  source_glob: string;
  file_count: number;
  row_count: number;
  latest_mtime_utc: string | null;
  parse_status: string;
  last_error: string | null;
}

export interface RaecRebalanceEvent {
  ny_date: string;
  strategy_id: string;
  regime: string;
  should_rebalance: boolean;
  rebalance_trigger: string;
  intent_count: number;
  portfolio_vol_target: number | null;
  posted: boolean;
}

export interface JournalRow {
  ny_date: string;
  ts_utc: string;
  strategy_id: string;
  intent_id: string;
  symbol: string;
  side: string;
  delta_pct: number;
  target_pct: number;
  current_pct: number;
  regime: string | null;
  posted: boolean | null;
}

export interface ReadinessStrategy {
  strategy_id: string;
  state_file_exists: boolean;
  last_eval_date: string | null;
  last_regime: string | null;
  has_allocations: boolean;
  allocation_count: number;
  total_weight_pct: number;
  ledger_files_today: number;
  warnings: string[];
}

export interface AllocationSnapshot {
  ny_date: string;
  strategy_id: string;
  symbol: string;
  weight_pct: number;
  alloc_type: string;
}

export interface SlippageSummary {
  mean_bps: number;
  median_bps: number;
  p95_bps: number;
  total: number;
}

export interface SlippageBucket {
  liquidity_bucket: string;
  count: number;
  mean_bps: number;
  min_bps: number;
  max_bps: number;
}

export interface SlippageTimeBucket {
  time_of_day_bucket: string;
  count: number;
  mean_bps: number;
}

export interface TradeAnalyticsStrategy {
  strategy_id: string;
  trade_count: number;
  unique_symbols: number;
  buys: number;
  sells: number;
}

export interface SymbolConcentration {
  symbol: string;
  count: number;
}

export interface PortfolioPosition {
  strategy_id: string;
  symbol: string;
  qty: number;
  avg_price: number | null;
  mark_price: number | null;
  notional: number;
  weight_pct: number;
}

export interface PortfolioSummary {
  date_ny: string;
  capital_total: number;
  capital_cash: number;
  capital_invested: number;
  gross_exposure: number;
  net_exposure: number;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  fees_today: number;
}

export interface StrategyMatrixRow {
  strategy_id: string;
  strategy_type: string;
  trade_count: number;
  unique_symbols: number;
  latest_regime: string | null;
  exposure: number | null;
}

export interface SymbolOverlap {
  symbol: string;
  strategy_ids: string[];
}
