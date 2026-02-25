import type { ApiEnvelope, FreshnessRow, KeyValue, TimePoint, TradeInstructionsPayload } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

async function get<T>(path: string): Promise<ApiEnvelope<T>> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as ApiEnvelope<T>;
}

async function post<T>(path: string, body: unknown): Promise<ApiEnvelope<T>> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`API POST ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as ApiEnvelope<T>;
}

async function put<T>(path: string, body: unknown): Promise<ApiEnvelope<T>> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`API PUT ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as ApiEnvelope<T>;
}

async function del<T>(path: string): Promise<ApiEnvelope<T>> {
  const response = await fetch(`${API_BASE}${path}`, { method: "DELETE" });
  if (!response.ok) {
    throw new Error(`API DELETE ${path} failed with status ${response.status}`);
  }
  return (await response.json()) as ApiEnvelope<T>;
}

export const api = {
  health: () => get<KeyValue>("/api/v1/health"),
  freshness: () => get<{ rows: FreshnessRow[] }>("/api/v1/freshness"),
  overview: (start?: string, end?: string) =>
    get<KeyValue>(`/api/v1/overview${toQuery({ start, end })}`),
  strategiesCompare: (start?: string, end?: string) =>
    get<KeyValue>(`/api/v1/strategies/compare${toQuery({ start, end })}`),
  decisionsTimeseries: (start?: string, end?: string) =>
    get<{ granularity: string; points: TimePoint[] }>(
      `/api/v1/decisions/timeseries${toQuery({ start, end, granularity: "day" })}`
    ),
  s2Signals: (args: {
    date?: string;
    symbol?: string;
    eligible?: boolean;
    selected?: boolean;
    reason_code?: string;
    limit?: number;
  }) => get<KeyValue>(`/api/v1/signals/s2${toQuery(args)}`),
  riskControls: (start?: string, end?: string) =>
    get<KeyValue>(`/api/v1/risk/controls${toQuery({ start, end })}`),
  backtestRuns: () => get<{ runs: KeyValue[] }>("/api/v1/backtests/runs"),
  backtestRun: (runId: string) => get<KeyValue>(`/api/v1/backtests/runs/${encodeURIComponent(runId)}`),
  exportUrl: (dataset: string, start?: string, end?: string) =>
    `${API_BASE}/api/v1/exports/${dataset}.csv${toQuery({ start, end })}`,

  raecDashboard: (args?: { start?: string; end?: string; strategy_id?: string; book_id?: string }) =>
    get<KeyValue>(`/api/v1/raec/dashboard${toQuery(args ?? {})}`),

  journal: (args?: {
    start?: string;
    end?: string;
    strategy_id?: string;
    book_id?: string;
    symbol?: string;
    side?: string;
    limit?: number;
  }) => get<KeyValue>(`/api/v1/journal${toQuery(args ?? {})}`),

  raecReadiness: () => get<KeyValue>("/api/v1/raec/readiness"),

  pnl: (args?: { start?: string; end?: string; strategy_id?: string; book_id?: string }) =>
    get<KeyValue>(`/api/v1/pnl${toQuery(args ?? {})}`),

  slippage: (args?: { start?: string; end?: string; strategy_id?: string }) =>
    get<KeyValue>(`/api/v1/execution/slippage${toQuery(args ?? {})}`),

  tradeAnalytics: (args?: { start?: string; end?: string; strategy_id?: string; book_id?: string }) =>
    get<KeyValue>(`/api/v1/analytics/trades${toQuery(args ?? {})}`),

  portfolioOverview: (args?: { start?: string; end?: string }) =>
    get<KeyValue>(`/api/v1/portfolio/overview${toQuery(args ?? {})}`),

  portfolioPositions: (args?: { date?: string }) =>
    get<KeyValue>(`/api/v1/portfolio/positions${toQuery(args ?? {})}`),

  portfolioHistory: (args?: { start?: string; end?: string }) =>
    get<KeyValue>(`/api/v1/portfolio/history${toQuery(args ?? {})}`),

  strategyMatrix: () => get<KeyValue>("/api/v1/strategies/matrix"),

  schwabOverview: (args?: { start?: string; end?: string }) =>
    get<KeyValue>(`/api/v1/schwab/overview${toQuery(args ?? {})}`),

  schwabTradeInstructions: () =>
    get<TradeInstructionsPayload>("/api/v1/schwab/trade-instructions"),

  performance: (args?: { start?: string; end?: string; strategy_id?: string; book_id?: string }) =>
    get<KeyValue>(`/api/v1/performance${toQuery(args ?? {})}`),

  todaysTrades: (args?: { date?: string }) =>
    get<KeyValue>(`/api/v1/trade/today${toQuery(args ?? {})}`),

  scanCandidates: (args?: {
    date?: string;
    symbol?: string;
    direction?: string;
    sector?: string;
    limit?: number;
  }) => get<KeyValue>(`/api/v1/scan/candidates${toQuery(args ?? {})}`),

  scanChartData: (symbol: string, anchor?: string | null, days?: number) =>
    get<KeyValue>(
      `/api/v1/scan/chart-data/${encodeURIComponent(symbol)}${toQuery({ anchor: anchor ?? undefined, days })}`,
    ),

  tradeLogList: (args?: { status?: string; symbol?: string; limit?: number }) =>
    get<KeyValue>(`/api/v1/trades/log${toQuery(args ?? {})}`),
  tradeLogSummary: () => get<KeyValue>("/api/v1/trades/log/summary"),
  tradeLogCreate: (body: Record<string, unknown>) =>
    post<KeyValue>("/api/v1/trades/log", body),
  tradeLogClose: (id: string, body: Record<string, unknown>) =>
    put<KeyValue>(`/api/v1/trades/log/${encodeURIComponent(id)}`, body),
  tradeLogDelete: (id: string) =>
    del<KeyValue>(`/api/v1/trades/log/${encodeURIComponent(id)}`),
};

function toQuery(params: Record<string, unknown>): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") {
      return;
    }
    sp.set(key, String(value));
  });
  const q = sp.toString();
  return q ? `?${q}` : "";
}
