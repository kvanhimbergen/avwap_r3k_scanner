/**
 * Command Center — the home dashboard.
 * Focused on: "How is the system performing?" and "What happened today?"
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

import { api } from "../api";
import { StatCard } from "../components/StatCard";
import { StatusBadge, RegimeBadge } from "../components/Badge";
import { SkeletonCard } from "../components/Skeleton";
import { ErrorState } from "../components/ErrorState";
import { usePolling } from "../hooks/usePolling";
import { formatCurrency, formatPercent, pnlColor } from "../lib/format";
import { getMeta } from "../lib/strategies";
import type {
  KeyValue,
  SchwabAccountBalance,
  SchwabPosition,
  SchwabPerformancePayload,
  TradeInstruction,
  TradeInstructionsPayload,
  TradeLogSummary,
} from "../types";

/* ── Helpers ──────────────────────────────────────── */

function todayNY(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

type DatePreset = "all" | "30d" | "90d";

function getDateRange(preset: DatePreset): { start?: string } {
  if (preset === "all") return {};
  const days = preset === "30d" ? 30 : 90;
  const start = new Date(Date.now() - days * 86_400_000);
  return { start: start.toISOString().slice(0, 10) };
}

const CHART_TOOLTIP = { backgroundColor: "#111827", border: "1px solid #1f2937", borderRadius: 6, fontSize: 12 };

/* ── Component ────────────────────────────────────── */

export function CommandCenter() {
  const [datePreset, setDatePreset] = useState<DatePreset>("all");
  const range = getDateRange(datePreset);

  const date = todayNY();

  // API calls
  const schwab = usePolling(() => api.schwabOverview(), 60_000);
  const perfPoll = usePolling(() => api.schwabPerformance(range), 60_000);
  const trades = usePolling(() => api.todaysTrades({ date }), 30_000);
  const instructions = usePolling(() => api.schwabTradeInstructions(), 60_000);
  const portfolio = usePolling(() => api.portfolioOverview(), 60_000);
  const tradeLog = usePolling(() => api.tradeLogSummary(), 60_000);

  // Extract data
  const schwabData = schwab.data?.data as Record<string, unknown> | undefined;
  const latestAccount = schwabData?.latest_account as SchwabAccountBalance | null;
  const positions = (schwabData?.positions ?? []) as SchwabPosition[];
  const perfData = perfPoll.data?.data as SchwabPerformancePayload | undefined;

  const tradeData = (trades.data?.data ?? {}) as Record<string, unknown>;
  const events = (tradeData.events ?? []) as Record<string, unknown>[];
  const anyRebalance = tradeData.any_rebalance as boolean | undefined;
  const hasTrades = tradeData.has_trades as boolean | undefined;

  const instructionsData = instructions.data?.data as TradeInstructionsPayload | undefined;
  const actionableCount = instructionsData?.days?.reduce((sum, d) => sum + d.actionable_count, 0) ?? 0;
  const actionableDollars = instructionsData?.days?.flatMap(d => d.intents).filter(i => i.actionable).reduce((sum, i) => sum + Math.abs(i.dollar_amount), 0) ?? 0;

  const portfolioData = (portfolio.data?.data ?? {}) as Record<string, unknown>;
  const latest = portfolioData.latest as Record<string, unknown> | undefined;
  const alpacaEquity = latest?.capital_total as number | undefined;
  const alpacaDayPnl = (latest?.realized_pnl ?? latest?.unrealized_pnl) as number | undefined;

  const logSummary = tradeLog.data?.data as TradeLogSummary | undefined;

  // Latest regime from today's events
  const latestRegime = events.length > 0 ? (events[events.length - 1].regime as string | null) : null;
  // Has the coordinator run today?
  const coordinatorRan = tradeData.coordinator != null || events.length > 0;

  const isLoading = schwab.loading && perfPoll.loading;
  const error = schwab.error || perfPoll.error;

  if (isLoading) {
    return (
      <div className="space-y-4 h-full">
        <div className="grid grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
        <div className="grid grid-cols-5 gap-4">
          {[...Array(5)].map((_, i) => <SkeletonCard key={i} />)}
        </div>
      </div>
    );
  }

  if (error) return <ErrorState message={error} />;

  return (
    <div className="space-y-4 h-full">
      {/* Row 1: Hero Strip */}
      <div className="grid grid-cols-4 gap-4">
        <StatCard
          label="Account Value"
          value={latestAccount?.total_value != null ? formatCurrency(latestAccount.total_value, 0) : "\u2014"}
          subtitle={latestAccount?.ny_date ? `as of ${latestAccount.ny_date}` : undefined}
        />
        <StatCard
          label="Return"
          value={perfData?.metrics.portfolio_return != null ? formatPercent(perfData.metrics.portfolio_return) : "\u2014"}
          numericValue={perfData?.metrics.portfolio_return}
          subtitle={perfData?.metrics.start_date ? `since ${perfData.metrics.start_date}` : undefined}
        />
        <StatCard
          label="vs SPY"
          value={perfData?.metrics.excess_vs_spy != null ? formatPercent(perfData.metrics.excess_vs_spy) : "\u2014"}
          numericValue={perfData?.metrics.excess_vs_spy}
        />
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4 min-w-0">
          <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Regime</p>
          <div className="mt-1">
            {latestRegime ? (
              <RegimeBadge regime={latestRegime} />
            ) : (
              <span className="font-mono text-2xl font-bold text-vantage-text">{"\u2014"}</span>
            )}
          </div>
        </div>
      </div>

      {/* Row 2: Performance Chart + Today's Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Performance Chart (60%) */}
        <div className="lg:col-span-3 bg-vantage-card border border-vantage-border rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Performance vs Market</h3>
            <div className="flex items-center gap-1">
              {(["all", "30d", "90d"] as DatePreset[]).map((p) => (
                <button
                  key={p}
                  onClick={() => setDatePreset(p)}
                  className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
                    datePreset === p ? "bg-vantage-border text-vantage-text" : "text-vantage-muted hover:text-vantage-text"
                  }`}
                >
                  {p === "all" ? "All" : p}
                </button>
              ))}
            </div>
          </div>
          {!perfData?.data_sufficient ? (
            <p className="text-xs text-vantage-muted py-4 text-center">Need 2+ account snapshots for performance chart</p>
          ) : (
            <>
              {/* KPI row */}
              <div className="grid grid-cols-5 gap-4 mb-4">
                {[
                  { label: "Portfolio", value: perfData.metrics.portfolio_return, suffix: "%" },
                  { label: "SPY", value: perfData.metrics.spy_return, suffix: "%" },
                  { label: "VTI", value: perfData.metrics.vti_return, suffix: "%" },
                  { label: "vs SPY", value: perfData.metrics.excess_vs_spy, suffix: "%" },
                  { label: "vs VTI", value: perfData.metrics.excess_vs_vti, suffix: "%" },
                ].map((m) => (
                  <div key={m.label}>
                    <p className="text-[10px] text-vantage-muted uppercase tracking-wide">{m.label}</p>
                    <p className={`font-mono text-lg font-bold ${m.value != null ? pnlColor(m.value) : "text-vantage-text"}`}>
                      {m.value != null ? `${m.value >= 0 ? "+" : ""}${m.value.toFixed(2)}${m.suffix}` : "\u2014"}
                    </p>
                  </div>
                ))}
              </div>
              {/* Chart */}
              {perfData.series.length >= 2 && (
                <div className="h-[280px]">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={perfData.series}>
                      <XAxis dataKey="date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9ca3af" }} />
                      <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9ca3af" }} tickFormatter={(v: number) => `${v}%`} />
                      <Tooltip contentStyle={CHART_TOOLTIP} formatter={(value: number) => [`${value.toFixed(2)}%`]} />
                      <ReferenceLine y={0} stroke="#374151" strokeDasharray="3 3" />
                      <Line type="monotone" dataKey="portfolio" name="Portfolio" stroke="#3b82f6" strokeWidth={2} dot={false} />
                      <Line type="monotone" dataKey="spy" name="SPY" stroke="#9ca3af" strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
                      <Line type="monotone" dataKey="vti" name="VTI" stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="6 3" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </>
          )}
        </div>

        {/* Today's Activity (40%) */}
        <div className="lg:col-span-2 bg-vantage-card border border-vantage-border rounded-lg p-4 flex flex-col">
          <h3 className="text-sm font-semibold mb-3">Today's Activity</h3>

          {!coordinatorRan ? (
            <p className="text-xs text-vantage-muted py-4 text-center">Coordinator has not run yet today</p>
          ) : (
            <div className="space-y-3 flex-1">
              {/* Verdict banner */}
              <div className={`rounded-md px-3 py-2 text-xs font-semibold ${
                anyRebalance
                  ? "bg-vantage-amber/10 text-vantage-amber"
                  : "bg-vantage-green/10 text-vantage-green"
              }`}>
                {anyRebalance
                  ? `Rebalance triggered \u2014 ${actionableCount} trade${actionableCount !== 1 ? "s" : ""}`
                  : "No trades needed today"}
              </div>

              {/* Strategy rows */}
              <div className="space-y-2">
                {events.map((ev, i) => {
                  const sid = ev.strategy_id as string;
                  const meta = getMeta(sid);
                  const regime = ev.regime as string | null;
                  const shouldRebalance = ev.should_rebalance as boolean;
                  return (
                    <div key={i} className="flex items-center gap-2 text-xs">
                      <span
                        className="w-2 h-2 rounded-full shrink-0"
                        style={{ backgroundColor: meta.color }}
                      />
                      <span className="font-mono font-semibold w-8 shrink-0">{meta.shortName}</span>
                      <RegimeBadge regime={regime} />
                      <span className="ml-auto">
                        <StatusBadge variant={shouldRebalance ? "warning" : "active"}>
                          {shouldRebalance ? "REBALANCE" : "HOLD"}
                        </StatusBadge>
                      </span>
                    </div>
                  );
                })}
              </div>

              {/* Actionable trades link */}
              {actionableCount > 0 && (
                <div className="mt-auto pt-3 border-t border-vantage-border">
                  <Link
                    to="/trade"
                    className="flex items-center justify-between text-xs text-vantage-blue hover:text-vantage-blue/80 transition-colors"
                  >
                    <span>
                      <span className="font-mono font-bold">{actionableCount}</span> trade{actionableCount !== 1 ? "s" : ""}
                      {actionableDollars > 0 && <span className="text-vantage-muted ml-1">({formatCurrency(actionableDollars, 0)})</span>}
                    </span>
                    <span>View trade tickets &rarr;</span>
                  </Link>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Row 3: Rebalance Snapshot + Alpaca Paper */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Rebalance Snapshot (60%) */}
        <div className="lg:col-span-3 bg-vantage-card border border-vantage-border rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold">Rebalance Snapshot</h3>
            {actionableCount > 0 ? (
              <StatusBadge variant="warning">{actionableCount} trade{actionableCount !== 1 ? "s" : ""} needed</StatusBadge>
            ) : coordinatorRan ? (
              <StatusBadge variant="active">ALIGNED</StatusBadge>
            ) : null}
          </div>
          {positions.length === 0 ? (
            <p className="text-xs text-vantage-muted py-4 text-center">No positions found</p>
          ) : (() => {
            // Merge positions with today's trade instructions
            const todayIntents = instructionsData?.days?.flatMap(d => d.intents) ?? [];
            const intentBySymbol = new Map<string, TradeInstruction>();
            for (const intent of todayIntents) intentBySymbol.set(intent.symbol, intent);

            // Build unified rows: every position + any intent-only symbols
            const symbolsSeen = new Set<string>();
            const rows: { symbol: string; value: number | null; currentPct: number | null; targetPct: number | null; tradeDollars: number | null; side: string | null; actionable: boolean }[] = [];

            for (const p of [...positions].sort((a, b) => (b.weight_pct ?? 0) - (a.weight_pct ?? 0))) {
              symbolsSeen.add(p.symbol);
              const intent = intentBySymbol.get(p.symbol);
              rows.push({
                symbol: p.symbol,
                value: p.market_value,
                currentPct: intent ? intent.current_pct : p.weight_pct,
                targetPct: intent ? intent.target_pct : p.weight_pct,
                tradeDollars: intent ? intent.dollar_amount : null,
                side: intent ? intent.side : null,
                actionable: intent?.actionable ?? false,
              });
            }
            // Add intent-only symbols (new positions to open)
            for (const intent of todayIntents) {
              if (!symbolsSeen.has(intent.symbol)) {
                rows.push({
                  symbol: intent.symbol,
                  value: null,
                  currentPct: intent.current_pct,
                  targetPct: intent.target_pct,
                  tradeDollars: intent.dollar_amount,
                  side: intent.side,
                  actionable: intent.actionable,
                });
              }
            }

            return (
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-vantage-border">
                    <th className="py-2 px-2 text-left text-vantage-muted font-medium">Symbol</th>
                    <th className="py-2 px-2 text-right text-vantage-muted font-medium">Value</th>
                    <th className="py-2 px-2 text-right text-vantage-muted font-medium">Current</th>
                    <th className="py-2 px-2 text-right text-vantage-muted font-medium">Target</th>
                    <th className="py-2 px-2 text-right text-vantage-muted font-medium">Trade</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const hasTrade = r.tradeDollars != null && r.actionable;
                    const isBuy = r.side === "BUY";
                    return (
                      <tr
                        key={r.symbol}
                        className={`border-b border-vantage-border/50 ${
                          hasTrade ? (isBuy ? "bg-vantage-green/[0.03]" : "bg-vantage-red/[0.03]") : ""
                        }`}
                      >
                        <td className="py-2 px-2 font-mono font-semibold">{r.symbol}</td>
                        <td className="py-2 px-2 font-mono text-right">{formatCurrency(r.value, 0)}</td>
                        <td className="py-2 px-2 font-mono text-right">{r.currentPct != null ? `${r.currentPct.toFixed(1)}%` : "\u2014"}</td>
                        <td className="py-2 px-2 font-mono text-right font-semibold">{r.targetPct != null ? `${r.targetPct.toFixed(1)}%` : "\u2014"}</td>
                        <td className={`py-2 px-2 font-mono text-right font-semibold ${
                          hasTrade ? (isBuy ? "text-vantage-green" : "text-vantage-red") : "text-vantage-muted"
                        }`}>
                          {hasTrade
                            ? `${isBuy ? "+" : "\u2212"}${formatCurrency(Math.abs(r.tradeDollars!), 0)}`
                            : r.tradeDollars != null
                              ? <span className="opacity-40">{formatCurrency(Math.abs(r.tradeDollars), 0)}</span>
                              : "\u2014"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            );
          })()}
          {actionableCount > 0 && (
            <div className="mt-3 pt-3 border-t border-vantage-border">
              <Link to="/trade" className="text-xs text-vantage-blue hover:text-vantage-blue/80 transition-colors">
                View full trade tickets &rarr;
              </Link>
            </div>
          )}
        </div>

        {/* Alpaca Paper (40%) */}
        <div className="lg:col-span-2 bg-vantage-card border border-vantage-border rounded-lg p-4 flex flex-col">
          <h3 className="text-sm font-semibold mb-3">Alpaca Paper</h3>
          <div className="space-y-3 flex-1">
            <div>
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Equity</p>
              <p className="font-mono text-lg font-bold">
                {alpacaEquity != null ? formatCurrency(alpacaEquity, 0) : "\u2014"}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Day P&L</p>
              <p className={`font-mono text-lg font-bold ${pnlColor(alpacaDayPnl)}`}>
                {alpacaDayPnl != null ? formatCurrency(alpacaDayPnl, 0) : "\u2014"}
              </p>
            </div>
            <div>
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Open Swing Trades</p>
              <p className="font-mono text-lg font-bold">
                {logSummary?.open_count != null ? logSummary.open_count : "\u2014"}
              </p>
            </div>
            <div className="mt-auto pt-3 border-t border-vantage-border">
              <Link
                to="/trade-log"
                className="text-xs text-vantage-blue hover:text-vantage-blue/80 transition-colors"
              >
                View trade log &rarr;
              </Link>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
