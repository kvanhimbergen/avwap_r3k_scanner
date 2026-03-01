/**
 * Performance — /performance
 * Portfolio metrics, benchmarking, and order activity.
 */
import { useState } from "react";
import { TrendingUp } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";

import { api } from "../api";
import { usePageTitle } from "../hooks/usePageTitle";
import { SkeletonCard, SkeletonChart } from "../components/Skeleton";
import { usePolling } from "../hooks/usePolling";
import { formatCurrency, formatPercent, formatNumber, pnlColor } from "../lib/format";
import type { PortfolioMetrics, SwingMetrics, RaecStrategyMetrics, OrderLogEntry } from "../types";

type DatePreset = "all" | "30d" | "90d";

function getDateRange(preset: DatePreset): { start?: string } {
  if (preset === "all") return {};
  const days = preset === "30d" ? 30 : 90;
  const start = new Date(Date.now() - days * 86_400_000);
  return { start: start.toISOString().slice(0, 10) };
}

const CHART_TOOLTIP = { backgroundColor: "#111827", border: "1px solid #1f2937", borderRadius: 6, fontSize: 12 };

export function PerformancePage() {
  usePageTitle("Performance");
  const [bookFilter, setBookFilter] = useState("");
  const [datePreset, setDatePreset] = useState<DatePreset>("all");

  const range = getDateRange(datePreset);
  const poll = usePolling(() => api.performance({ ...range, book_id: bookFilter || undefined }), 60_000);

  const data = poll.data?.data as Record<string, unknown> | undefined;
  const swingMetrics = (data?.swing_metrics ?? {}) as Record<string, SwingMetrics>;
  const portfolioMetrics = (data?.portfolio_metrics ?? {}) as PortfolioMetrics;
  const raecMetrics = (data?.raec_metrics ?? {}) as Record<string, RaecStrategyMetrics>;
  const orderLog = (data?.order_log ?? []) as OrderLogEntry[];
  const equityCurve = portfolioMetrics?.equity_curve ?? [];
  const isUp = equityCurve.length >= 2 && equityCurve[equityCurve.length - 1].capital_total >= equityCurve[0].capital_total;
  const curveColor = isUp ? "#10b981" : "#ef4444";

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <TrendingUp size={24} className="text-vantage-green" />
          <div>
            <h2 className="text-xl font-semibold">Performance</h2>
            <p className="text-[11px] text-vantage-muted">Strategy performance metrics and benchmarking</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <select value={bookFilter} onChange={(e) => setBookFilter(e.target.value)} className="bg-vantage-bg border border-vantage-border rounded px-2.5 py-1.5 text-xs text-vantage-text focus:outline-none focus:border-vantage-blue/50">
            <option value="">All Books</option>
            <option value="ALPACA_PAPER">Alpaca Paper</option>
          </select>
          <div className="flex items-center gap-1">
            {(["all", "30d", "90d"] as DatePreset[]).map((p) => (
              <button key={p} onClick={() => setDatePreset(p)} className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${datePreset === p ? "bg-vantage-border text-vantage-text" : "text-vantage-muted hover:text-vantage-text"}`}>
                {p === "all" ? "All" : p}
              </button>
            ))}
          </div>
        </div>
      </div>

      {poll.loading ? (
        <div className="space-y-4">
          <div className="grid grid-cols-4 gap-4">{[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}</div>
          <SkeletonChart />
        </div>
      ) : (
        <>
          {/* Portfolio Metrics */}
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">Portfolio Performance (vs {portfolioMetrics?.benchmark ?? "SPY"})</h3>
            {!portfolioMetrics?.data_sufficient ? (
              <p className="text-xs text-vantage-muted py-4">Need 10+ portfolio snapshots for metrics</p>
            ) : (
              <>
                <div className="grid grid-cols-2 lg:grid-cols-4 xl:grid-cols-7 gap-4 mb-4">
                  {[
                    { label: "Total Return", value: formatPercent(portfolioMetrics.total_return != null ? portfolioMetrics.total_return * 100 : null), num: portfolioMetrics.total_return },
                    { label: "SPY Return", value: formatPercent(portfolioMetrics.benchmark_return != null ? portfolioMetrics.benchmark_return * 100 : null) },
                    { label: "Excess", value: formatPercent(portfolioMetrics.excess_return != null ? portfolioMetrics.excess_return * 100 : null), num: portfolioMetrics.excess_return },
                    { label: "Sharpe", value: formatNumber(portfolioMetrics.sharpe_ratio) },
                    { label: "Sortino", value: formatNumber(portfolioMetrics.sortino_ratio) },
                    { label: "Max DD", value: formatPercent(portfolioMetrics.max_drawdown != null ? portfolioMetrics.max_drawdown * 100 : null), num: portfolioMetrics.max_drawdown },
                    { label: "Calmar", value: formatNumber(portfolioMetrics.calmar_ratio) },
                  ].map((m) => (
                    <div key={m.label}>
                      <p className="text-[10px] text-vantage-muted uppercase tracking-wide">{m.label}</p>
                      <p className={`font-mono text-lg font-bold ${m.num != null ? pnlColor(m.num) : "text-vantage-text"}`}>{m.value}</p>
                    </div>
                  ))}
                </div>
                {equityCurve.length >= 2 && (
                  <div className="h-[280px]">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart data={equityCurve}>
                        <defs>
                          <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" stopColor={curveColor} stopOpacity={0.3} />
                            <stop offset="100%" stopColor={curveColor} stopOpacity={0} />
                          </linearGradient>
                        </defs>
                        <XAxis dataKey="date_ny" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9ca3af" }} />
                        <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9ca3af" }} />
                        <Tooltip contentStyle={CHART_TOOLTIP} />
                        <Area type="monotone" dataKey="capital_total" stroke={curveColor} strokeWidth={2} fill="url(#equityGrad)" activeDot={{ r: 3, fill: curveColor }} />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </>
            )}
          </div>

          {/* Swing Metrics */}
          {Object.keys(swingMetrics).length > 0 && (
            <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">Swing Trade Metrics</h3>
              {Object.entries(swingMetrics).map(([sid, m]) => (
                <div key={sid} className="mb-4 last:mb-0">
                  <p className="text-xs font-semibold mb-2">{sid}</p>
                  {!m.data_sufficient ? (
                    <p className="text-xs text-vantage-muted">Need 5+ closed trades ({m.closed_trade_count} so far)</p>
                  ) : (
                    <div className="grid grid-cols-5 gap-4">
                      {[
                        { label: "Win Rate", value: m.win_rate != null ? `${(m.win_rate * 100).toFixed(1)}%` : "\u2014" },
                        { label: "Avg R", value: m.avg_r_multiple?.toFixed(2) ?? "\u2014" },
                        { label: "Expectancy", value: m.expectancy != null ? formatCurrency(m.expectancy) : "\u2014" },
                        { label: "Profit Factor", value: m.profit_factor?.toFixed(2) ?? "\u2014" },
                        { label: "Fill Rate", value: m.fill_rate != null ? `${(m.fill_rate * 100).toFixed(0)}%` : "\u2014" },
                      ].map((kpi) => (
                        <div key={kpi.label}>
                          <p className="text-[10px] text-vantage-muted uppercase tracking-wide">{kpi.label}</p>
                          <p className="font-mono text-sm font-semibold">{kpi.value}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* RAEC Metrics */}
          {Object.keys(raecMetrics).length > 0 && (
            <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
              <h3 className="text-sm font-semibold mb-3">RAEC Strategy Metrics</h3>
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-vantage-border">
                    <th className="py-2 px-2 text-left text-vantage-muted font-medium">Strategy</th>
                    <th className="py-2 px-2 text-right text-vantage-muted font-medium">Rebalances</th>
                    <th className="py-2 px-2 text-right text-vantage-muted font-medium">Avg Turnover</th>
                    <th className="py-2 px-2 text-right text-vantage-muted font-medium">Regime Changes</th>
                    <th className="py-2 px-2 text-left text-vantage-muted font-medium">Current Regime</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(raecMetrics).map(([sid, m]) => (
                    <tr key={sid} className="border-b border-vantage-border/50">
                      <td className="py-2 px-2 font-semibold">{sid}</td>
                      <td className="py-2 px-2 font-mono text-right">{m.rebalance_count}</td>
                      <td className="py-2 px-2 font-mono text-right">{m.avg_turnover_pct != null ? `${m.avg_turnover_pct}%` : "\u2014"}</td>
                      <td className="py-2 px-2 font-mono text-right">{m.regime_changes}</td>
                      <td className="py-2 px-2">{m.current_regime ?? "\u2014"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Order Log */}
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <h3 className="text-sm font-semibold mb-3">
              Order Log <span className="text-vantage-muted font-normal">({orderLog.length})</span>
            </h3>
            {orderLog.length === 0 ? (
              <p className="text-xs text-vantage-muted py-4 text-center">No order events found</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-vantage-border">
                      <th className="py-2 px-2 text-left text-vantage-muted font-medium">Date</th>
                      <th className="py-2 px-2 text-left text-vantage-muted font-medium">Symbol</th>
                      <th className="py-2 px-2 text-left text-vantage-muted font-medium">Side</th>
                      <th className="py-2 px-2 text-right text-vantage-muted font-medium">Qty</th>
                      <th className="py-2 px-2 text-right text-vantage-muted font-medium">Ref Price</th>
                      <th className="py-2 px-2 text-right text-vantage-muted font-medium">Filled</th>
                      <th className="py-2 px-2 text-right text-vantage-muted font-medium">Fill Price</th>
                      <th className="py-2 px-2 text-left text-vantage-muted font-medium">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orderLog.map((o, i) => (
                      <tr key={`${o.alpaca_order_id}-${i}`} className="border-b border-vantage-border/50">
                        <td className="py-2 px-2 font-mono">{o.date_ny}</td>
                        <td className="py-2 px-2 font-mono font-semibold">{o.symbol}</td>
                        <td className={`py-2 px-2 font-mono font-semibold ${o.side === "buy" ? "text-vantage-green" : "text-vantage-red"}`}>{o.side}</td>
                        <td className="py-2 px-2 font-mono text-right">{o.qty?.toLocaleString() ?? "\u2014"}</td>
                        <td className="py-2 px-2 font-mono text-right">{o.ref_price != null ? formatCurrency(o.ref_price) : "\u2014"}</td>
                        <td className="py-2 px-2 font-mono text-right">{o.filled_qty?.toLocaleString() ?? "\u2014"}</td>
                        <td className="py-2 px-2 font-mono text-right">{o.filled_avg_price != null ? formatCurrency(o.filled_avg_price) : "\u2014"}</td>
                        <td className="py-2 px-2">{o.status}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
