import { useState } from "react";
import { Bar, BarChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, Cell } from "recharts";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";

const STRATEGIES = [
  { id: "", label: "All Strategies" },
  { id: "S1_AVWAP_CORE", label: "S1 AVWAP Core" },
  { id: "S2_LETF_ORB_AGGRO", label: "S2 LETF ORB" },
];

const BUCKET_COLORS: Record<string, string> = {
  mega: "#0f9d58",
  large: "#1f6feb",
  mid: "#dd6b20",
  small: "#db4437",
};

export function SlippagePage() {
  const [strategyId, setStrategyId] = useState("");
  const slippage = usePolling(
    () => api.slippage({ strategy_id: strategyId || undefined }),
    60_000,
  );

  if (slippage.loading) return <LoadingState text="Loading slippage data..." />;
  if (slippage.error) return <ErrorState error={slippage.error} />;

  const data = slippage.data?.data as Record<string, any> ?? {};
  const summary = data.summary ?? {};
  const byBucket = data.by_bucket ?? [];
  const byTime = data.by_time ?? [];
  const bySymbol = data.by_symbol ?? [];
  const trend = data.trend ?? [];

  const slippageClass = (bps: number) =>
    bps <= 5 ? "slippage-good" : bps <= 15 ? "slippage-warn" : "slippage-bad";

  return (
    <section>
      <h2 className="page-title">Execution Slippage</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          Slippage measures the difference between the <strong>ideal fill price</strong> (benchmark)
          and the <strong>actual fill price</strong> in basis points. Lower is better.
          Monitor by <strong>liquidity bucket</strong> to understand market impact and by
          <strong> time of day</strong> to optimize execution timing.
        </p>
      </div>

      <div className="filter-bar">
        <label>
          Strategy:{" "}
          <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
            {STRATEGIES.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>

      <div className="kpi-grid">
        <KpiCard label="Mean Slippage" value={`${(summary.mean_bps ?? 0).toFixed(1)} bps`} />
        <KpiCard label="Median Slippage" value={`${(summary.median_bps ?? 0).toFixed(1)} bps`} />
        <KpiCard label="P95 Slippage" value={`${(summary.p95_bps ?? 0).toFixed(1)} bps`} />
        <KpiCard label="Total Executions" value={summary.total ?? 0} />
      </div>

      {/* By Liquidity Bucket */}
      {byBucket.length > 0 && (
        <div className="chart-card">
          <h3>Slippage by Liquidity Bucket</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byBucket}>
              <XAxis dataKey="liquidity_bucket" />
              <YAxis unit=" bps" />
              <Tooltip />
              <Bar dataKey="mean_bps">
                {byBucket.map((entry: any, idx: number) => (
                  <Cell key={idx} fill={BUCKET_COLORS[entry.liquidity_bucket] ?? "#1f6feb"} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* By Time of Day */}
      {byTime.length > 0 && (
        <div className="chart-card">
          <h3>Slippage by Time of Day</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={byTime}>
              <XAxis dataKey="time_of_day_bucket" angle={-45} textAnchor="end" height={80} />
              <YAxis unit=" bps" />
              <Tooltip />
              <Bar dataKey="mean_bps" fill="#8b5cf6" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Top Symbols by Slippage */}
      {bySymbol.length > 0 && (
        <div className="table-card">
          <h3>Top Symbols by Absolute Slippage</h3>
          <table>
            <thead>
              <tr><th>Symbol</th><th>Executions</th><th>Mean Slippage (bps)</th></tr>
            </thead>
            <tbody>
              {bySymbol.map((row: any) => (
                <tr key={row.symbol}>
                  <td>{row.symbol}</td>
                  <td>{row.count}</td>
                  <td className={slippageClass(Math.abs(row.mean_bps))}>{row.mean_bps.toFixed(1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Trend */}
      {trend.length > 0 && (
        <div className="chart-card">
          <h3>Daily Average Slippage Trend</h3>
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={trend}>
              <XAxis dataKey="date_ny" />
              <YAxis unit=" bps" />
              <Tooltip />
              <Line type="monotone" dataKey="mean_bps" stroke="#1f6feb" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </section>
  );
}
