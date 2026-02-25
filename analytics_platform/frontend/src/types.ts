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
  ts_utc: string | null;
  strategy_id: string;
  book_id: string | null;
  regime: string;
  should_rebalance: boolean;
  rebalance_trigger: string;
  intent_count: number;
  portfolio_vol_target: number | null;
  portfolio_vol_realized: number | null;
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
  book_id: string | null;
  state_file_exists: boolean;
  last_eval_date: string | null;
  last_regime: string | null;
  has_allocations: boolean;
  allocation_count: number;
  total_weight_pct: number;
  today_ledger_count: number;
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
  source: string;
  book_id: string | null;
  trade_count: number;
  rebalance_count?: number;
  unique_symbols: number;
  latest_regime: string | null;
  exposure: number | null;
}

export interface SymbolOverlap {
  symbol: string;
  strategy_ids: string[];
}

export interface SchwabAccountBalance {
  ny_date: string;
  as_of_utc: string;
  cash: number;
  market_value: number;
  total_value: number;
}

export interface SchwabPosition {
  symbol: string;
  qty: number;
  cost_basis: number;
  market_value: number;
  weight_pct: number;
}

export interface SchwabOrder {
  ny_date: string;
  order_id: string;
  symbol: string;
  side: string;
  qty: number;
  filled_qty: number;
  status: string;
  submitted_at: string | null;
  filled_at: string | null;
}

export interface ScanCandidate {
  scan_date: string;
  symbol: string;
  direction: string;
  trend_tier: string;
  price: number | null;
  entry_level: number | null;
  entry_dist_pct: number | null;
  stop_loss: number | null;
  target_r1: number | null;
  target_r2: number | null;
  trend_score: number | null;
  sector: string | null;
  anchor: string | null;
  avwap_slope: number | null;
  avwap_confluence: number | null;
  sector_rs: number | null;
  setup_vwap_control: string | null;
  setup_vwap_reclaim: string | null;
  setup_vwap_acceptance: string | null;
  setup_vwap_dist_pct: number | null;
  setup_avwap_control: string | null;
  setup_avwap_reclaim: string | null;
  setup_avwap_acceptance: string | null;
  setup_avwap_dist_pct: number | null;
  setup_extension_state: string | null;
  setup_gap_reset: string | null;
  setup_structure_state: string | null;
}

export interface SwingMetrics {
  closed_trade_count: number;
  open_trade_count: number;
  win_rate: number | null;
  avg_r_multiple: number | null;
  expectancy: number | null;
  profit_factor: number | null;
  fill_rate: number | null;
  avg_holding_days: number | null;
  max_consecutive_losers: number | null;
  gross_pnl: number;
  data_sufficient: boolean;
}

export interface PortfolioMetrics {
  total_return: number | null;
  annualized_return: number | null;
  sharpe_ratio: number | null;
  sortino_ratio: number | null;
  max_drawdown: number | null;
  calmar_ratio: number | null;
  data_points: number;
  equity_curve: { date_ny: string; capital_total: number }[];
  benchmark: string;
  benchmark_return: number | null;
  excess_return: number | null;
  benchmark_curve: { date_ny: string; close: number }[];
  data_sufficient: boolean;
}

export interface RaecStrategyMetrics {
  rebalance_count: number;
  avg_turnover_pct: number | null;
  regime_changes: number;
  current_regime: string | null;
  data_sufficient: boolean;
}

export interface OrderLogEntry {
  date_ny: string;
  ts_utc: string | null;
  book_id: string;
  strategy_id: string;
  symbol: string;
  qty: number | null;
  side: string;
  ref_price: number | null;
  filled_qty: number | null;
  filled_avg_price: number | null;
  status: string;
  order_type: string;
  stop_loss: number | null;
  take_profit: number | null;
  alpaca_order_id: string;
}

export interface TradeIntent {
  ny_date: string;
  ts_utc: string | null;
  strategy_id: string;
  intent_id: string;
  symbol: string;
  side: string;
  delta_pct: number;
  target_pct: number;
  current_pct: number;
}

export interface CoordinatorRun {
  ny_date: string;
  ts_utc: string | null;
  capital_split: Record<string, number>;
  sub_results: Record<string, unknown>;
}

export interface TradeLogEntry {
  id: string;
  created_utc: string;
  updated_utc: string;
  entry_date: string;
  symbol: string;
  direction: string;
  entry_price: number;
  qty: number;
  stop_loss: number;
  target_r1: number | null;
  target_r2: number | null;
  strategy_source: string | null;
  scan_date: string | null;
  notes: string | null;
  exit_date: string | null;
  exit_price: number | null;
  exit_reason: string | null;
  risk_per_share: number;
  r_multiple: number | null;
  pnl_dollars: number | null;
  status: string;
}

export interface TradeLogSummary {
  open_count: number;
  closed_count: number;
  wins: number;
  losses: number;
  win_rate: number | null;
  avg_r_multiple: number | null;
  total_pnl: number;
}

export interface SchwabReconciliation {
  ny_date: string;
  as_of_utc: string;
  broker_position_count: number;
  drift_symbol_count: number;
  drift_intent_count: number;
  drift_reason_codes_json: string;
  symbols_json: string;
}
