/**
 * Schwab Account — /ops/schwab
 * Live 401(k) positions, balances, and reconciliation.
 */
import { useState } from "react";
import { Landmark, AlertTriangle } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";

import { api } from "../api";
import { StatusBadge } from "../components/Badge";
import { SkeletonCard, SkeletonTable } from "../components/Skeleton";
import { TradeInstructionsPanel } from "../components/TradeInstructionsPanel";
import { usePolling } from "../hooks/usePolling";
import { formatCurrency, formatPercent, pnlColor } from "../lib/format";
import type { SchwabAccountBalance, SchwabPosition, SchwabOrder, SchwabReconciliation, TradeInstructionsPayload, SchwabPerformancePayload } from "../types";

type DatePreset = "all" | "30d" | "90d";

function getDateRange(preset: DatePreset): { start?: string } {
  if (preset === "all") return {};
  const days = preset === "30d" ? 30 : 90;
  const start = new Date(Date.now() - days * 86_400_000);
  return { start: start.toISOString().slice(0, 10) };
}

const CHART_TOOLTIP = { backgroundColor: "#111827", border: "1px solid #1f2937", borderRadius: 6, fontSize: 12 };

export function SchwabAccountPage() {
  const [datePreset, setDatePreset] = useState<DatePreset>("all");
  const range = getDateRange(datePreset);

  const poll = usePolling(() => api.schwabOverview(), 60_000);
  const instructionsPoll = usePolling(() => api.schwabTradeInstructions(), 60_000);
  const perfPoll = usePolling(() => api.schwabPerformance(range), 60_000);
  const data = poll.data?.data as Record<string, unknown> | undefined;
  const instructionsData = instructionsPoll.data?.data as TradeInstructionsPayload | undefined;
  const perfData = perfPoll.data?.data as SchwabPerformancePayload | undefined;

  const latestAccount = data?.latest_account as SchwabAccountBalance | null;
  const positions = (data?.positions ?? []) as SchwabPosition[];
  const orders = (data?.orders ?? []) as SchwabOrder[];
  const latestRecon = data?.latest_reconciliation as SchwabReconciliation | null;

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Landmark size={24} className="text-vantage-blue" />
        <div>
          <h2 className="text-xl font-semibold">Schwab Account</h2>
          <p className="text-[11px] text-vantage-muted">Live 401(k) positions, balances, and reconciliation</p>
        </div>
      </div>

      {/* Balance KPIs */}
      {poll.loading ? (
        <div className="grid grid-cols-4 gap-4">{[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}</div>
      ) : (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Total Value</p>
            <p className="font-mono text-2xl font-bold">{formatCurrency(latestAccount?.total_value, 0)}</p>
            {latestAccount?.ny_date && <p className="text-[10px] text-vantage-muted mt-1">{latestAccount.ny_date}</p>}
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Market Value</p>
            <p className="font-mono text-2xl font-bold">{formatCurrency(latestAccount?.market_value, 0)}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Cash</p>
            <p className="font-mono text-2xl font-bold">{formatCurrency(latestAccount?.cash, 0)}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">As Of</p>
            <p className="font-mono text-sm font-semibold">
              {latestAccount?.as_of_utc ? new Date(latestAccount.as_of_utc).toLocaleString() : "\u2014"}
            </p>
          </div>
        </div>
      )}

      {/* Trade Instructions */}
      {instructionsData && <TradeInstructionsPanel data={instructionsData} />}

      {/* Performance vs Market */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold">Performance vs Market</h3>
          <div className="flex items-center gap-1">
            {(["all", "30d", "90d"] as DatePreset[]).map((p) => (
              <button key={p} onClick={() => setDatePreset(p)} className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${datePreset === p ? "bg-vantage-border text-vantage-text" : "text-vantage-muted hover:text-vantage-text"}`}>
                {p === "all" ? "All" : p}
              </button>
            ))}
          </div>
        </div>
        {!perfData?.data_sufficient ? (
          <p className="text-xs text-vantage-muted py-4 text-center">Need 2+ account snapshots for performance chart</p>
        ) : (
          <>
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

      {/* Positions */}
      {poll.loading ? (
        <SkeletonTable />
      ) : (
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Positions ({positions.length})</h3>
          {positions.length === 0 ? (
            <p className="text-xs text-vantage-muted py-4 text-center">No positions found</p>
          ) : (
            <table className="w-full text-xs">
              <thead><tr className="border-b border-vantage-border">
                <th className="py-2 px-2 text-left text-vantage-muted font-medium">Symbol</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Qty</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Market Value</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Weight</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Cost Basis</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">P&L</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">P&L %</th>
              </tr></thead>
              <tbody>
                {positions.map((p) => {
                  const pl = p.market_value != null && p.cost_basis != null ? p.market_value - p.cost_basis : null;
                  const plPct = pl != null && p.cost_basis ? (pl / p.cost_basis) * 100 : null;
                  return (
                  <tr key={p.symbol} className="border-b border-vantage-border/50">
                    <td className="py-2 px-2 font-mono font-semibold">{p.symbol}</td>
                    <td className="py-2 px-2 font-mono text-right">{p.qty?.toLocaleString() ?? "\u2014"}</td>
                    <td className="py-2 px-2 font-mono text-right">{formatCurrency(p.market_value)}</td>
                    <td className="py-2 px-2 font-mono text-right">{formatPercent(p.weight_pct, 1)}</td>
                    <td className="py-2 px-2 font-mono text-right">{formatCurrency(p.cost_basis)}</td>
                    <td className={`py-2 px-2 font-mono text-right ${pnlColor(pl)}`}>{formatCurrency(pl)}</td>
                    <td className={`py-2 px-2 font-mono text-right ${pnlColor(plPct)}`}>{plPct != null ? `${plPct >= 0 ? "+" : ""}${plPct.toFixed(1)}%` : "\u2014"}</td>
                  </tr>);
                })}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Recent Orders */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3">Recent Orders</h3>
        {orders.length === 0 ? (
          <p className="text-xs text-vantage-muted py-4 text-center">No recent orders</p>
        ) : (
          <table className="w-full text-xs">
            <thead><tr className="border-b border-vantage-border">
              <th className="py-2 px-2 text-left text-vantage-muted font-medium">Date</th>
              <th className="py-2 px-2 text-left text-vantage-muted font-medium">Symbol</th>
              <th className="py-2 px-2 text-left text-vantage-muted font-medium">Side</th>
              <th className="py-2 px-2 text-right text-vantage-muted font-medium">Qty</th>
              <th className="py-2 px-2 text-right text-vantage-muted font-medium">Filled</th>
              <th className="py-2 px-2 text-left text-vantage-muted font-medium">Status</th>
            </tr></thead>
            <tbody>
              {orders.map((o) => (
                <tr key={o.order_id} className="border-b border-vantage-border/50">
                  <td className="py-2 px-2 font-mono">{o.ny_date}</td>
                  <td className="py-2 px-2 font-mono font-semibold">{o.symbol}</td>
                  <td className={`py-2 px-2 font-mono font-semibold ${o.side === "BUY" ? "text-vantage-green" : "text-vantage-red"}`}>{o.side}</td>
                  <td className="py-2 px-2 font-mono text-right">{o.qty?.toLocaleString() ?? "\u2014"}</td>
                  <td className="py-2 px-2 font-mono text-right">{o.filled_qty?.toLocaleString() ?? "\u2014"}</td>
                  <td className="py-2 px-2">{o.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Reconciliation */}
      {latestRecon && (
        <div className={`bg-vantage-card border rounded-lg p-4 ${latestRecon.drift_intent_count > 0 ? "border-vantage-amber/40" : "border-vantage-border"}`}>
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            Reconciliation
            <StatusBadge variant={latestRecon.drift_intent_count === 0 ? "active" : "warning"}>
              {latestRecon.drift_intent_count === 0 ? "OK" : "DRIFT"}
            </StatusBadge>
          </h3>
          <div className="grid grid-cols-4 gap-4">
            <div>
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Date</p>
              <p className="font-mono text-xs font-semibold">{latestRecon.ny_date}</p>
            </div>
            <div>
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Broker Positions</p>
              <p className="font-mono text-xs font-semibold">{latestRecon.broker_position_count}</p>
            </div>
            <div>
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Drift Symbols</p>
              <p className="font-mono text-xs font-semibold">{latestRecon.drift_symbol_count}</p>
            </div>
            <div>
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Drift Intents</p>
              <p className={`font-mono text-xs font-semibold ${latestRecon.drift_intent_count > 0 ? "text-vantage-amber" : ""}`}>{latestRecon.drift_intent_count}</p>
            </div>
          </div>
          {latestRecon.drift_reason_codes_json && latestRecon.drift_reason_codes_json !== "[]" && (
            <div className="mt-3 flex items-center gap-2 flex-wrap">
              <AlertTriangle size={12} className="text-vantage-amber" />
              {(JSON.parse(latestRecon.drift_reason_codes_json) as string[]).map((code) => (
                <span key={code} className="text-[10px] px-1.5 py-0.5 rounded font-bold bg-vantage-amber/15 text-vantage-amber">{code}</span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
