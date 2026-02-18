import type { ApiEnvelope, FreshnessRow, KeyValue, TimePoint } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "";

async function get<T>(path: string): Promise<ApiEnvelope<T>> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API ${path} failed with status ${response.status}`);
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

  raecDashboard: (args?: { start?: string; end?: string; strategy_id?: string }) =>
    get<KeyValue>(`/api/v1/raec/dashboard${toQuery(args ?? {})}`),

  journal: (args?: {
    start?: string;
    end?: string;
    strategy_id?: string;
    symbol?: string;
    side?: string;
    limit?: number;
  }) => get<KeyValue>(`/api/v1/journal${toQuery(args ?? {})}`),

  raecReadiness: () => get<KeyValue>("/api/v1/raec/readiness"),

  pnl: (args?: { start?: string; end?: string; strategy_id?: string }) =>
    get<KeyValue>(`/api/v1/pnl${toQuery(args ?? {})}`),
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
