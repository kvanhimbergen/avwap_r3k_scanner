/**
 * Risk Monitor — /risk
 * Regime, exposure, throttle events, decision pipeline.
 */
import { useMemo } from "react";
import { ShieldAlert } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, LineChart, Line } from "recharts";

import { api } from "../api";
import { RegimeBadge } from "../components/Badge";
import { SkeletonCard, SkeletonChart } from "../components/Skeleton";
import { ErrorState } from "../components/ErrorState";
import { useLayoutData } from "../context/LayoutDataContext";
import { usePolling } from "../hooks/usePolling";
import { formatCurrency } from "../lib/format";
import type { TimePoint } from "../types";

const CHART_TOOLTIP = { backgroundColor: "#111827", border: "1px solid #1f2937", borderRadius: 6, fontSize: 12 };

export function RiskPage() {
  const { portfolio } = useLayoutData();
  const risk = usePolling(() => api.riskControls(), 60_000);
  const decisions = usePolling(() => api.decisionsTimeseries(), 60_000);
  const pnl = usePolling(() => api.pnl(), 60_000);

  if (risk.error) return <ErrorState message={risk.error} />;

  const controls = ((risk.data?.data as any)?.risk_controls ?? []) as any[];
  const regimes = ((risk.data?.data as any)?.regimes ?? []) as any[];
  const decisionPoints = ((decisions.data?.data as any)?.points ?? []) as TimePoint[];
  const pnlData = (pnl.data?.data as any) ?? {};
  const allocationDrift: any[] = pnlData.allocation_drift ?? [];
  const byStrategy: any[] = pnlData.by_strategy ?? [];
  const portfolioData = ((portfolio.data?.data as any)?.latest ?? {}) as Record<string, unknown>;

  const latestRegime = regimes.length > 0 ? regimes[regimes.length - 1] : undefined;

  const decisionTotals = useMemo(() => {
    const cycles = decisionPoints.reduce((s, p) => s + p.cycle_count, 0);
    const intents = decisionPoints.reduce((s, p) => s + p.intent_count, 0);
    const accepted = decisionPoints.reduce((s, p) => s + p.accepted_count, 0);
    const rejected = decisionPoints.reduce((s, p) => s + p.rejected_count, 0);
    const gates = decisionPoints.reduce((s, p) => s + p.gate_blocks, 0);
    return { cycles, intents, accepted, rejected, gates };
  }, [decisionPoints]);

  return (
    <div className="p-6 space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ShieldAlert size={24} className={latestRegime?.regime_label?.includes("OFF") ? "text-vantage-red" : "text-vantage-green"} />
        <div>
          <h2 className="text-xl font-semibold">Risk Monitor</h2>
          <p className="text-[11px] text-vantage-muted">Regime, exposure, throttle events, and decision pipeline</p>
        </div>
      </div>

      {/* KPI Row */}
      {risk.loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}</div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Current Regime</p>
            <RegimeBadge regime={latestRegime?.regime_label ?? latestRegime?.regime_id ?? null} />
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Risk Multiplier</p>
            <p className="font-mono text-2xl font-bold">{controls[0]?.risk_multiplier ?? "\u2014"}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Gross Exposure</p>
            <p className="font-mono text-2xl font-bold">{portfolioData.gross_exposure != null ? formatCurrency(portfolioData.gross_exposure as number, 0) : "\u2014"}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Capital</p>
            <p className="font-mono text-2xl font-bold">{portfolioData.capital_total != null ? formatCurrency(portfolioData.capital_total as number, 0) : "\u2014"}</p>
          </div>
        </div>
      )}

      {/* Regime Timeline + Controls */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Regime Timeline</h3>
          {regimes.length === 0 ? (
            <p className="text-xs text-vantage-muted py-4 text-center">No regime data</p>
          ) : (
            <div className="overflow-y-auto max-h-[300px]">
              <table className="w-full text-xs">
                <thead><tr className="border-b border-vantage-border">
                  <th className="py-2 px-2 text-left text-vantage-muted font-medium">Date</th>
                  <th className="py-2 px-2 text-left text-vantage-muted font-medium">Regime</th>
                  <th className="py-2 px-2 text-left text-vantage-muted font-medium">Reasons</th>
                </tr></thead>
                <tbody>
                  {regimes.map((row: any, idx: number) => (
                    <tr key={`${row.ny_date}-${idx}`} className="border-b border-vantage-border/50">
                      <td className="py-2 px-2 font-mono">{row.ny_date}</td>
                      <td className="py-2 px-2"><RegimeBadge regime={row.regime_label ?? row.regime_id} /></td>
                      <td className="py-2 px-2 font-mono text-vantage-muted">{row.reason_codes_json ?? ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Risk Control Events</h3>
          {controls.length === 0 ? (
            <p className="text-xs text-vantage-muted py-4 text-center">No control events</p>
          ) : (
            <div className="overflow-y-auto max-h-[300px]">
              <table className="w-full text-xs">
                <thead><tr className="border-b border-vantage-border">
                  <th className="py-2 px-2 text-left text-vantage-muted font-medium">Date</th>
                  <th className="py-2 px-2 text-left text-vantage-muted font-medium">Source</th>
                  <th className="py-2 px-2 text-right text-vantage-muted font-medium">Risk Mult</th>
                  <th className="py-2 px-2 text-left text-vantage-muted font-medium">Reason</th>
                </tr></thead>
                <tbody>
                  {controls.map((row: any, idx: number) => (
                    <tr key={`${row.source_type}-${idx}`} className="border-b border-vantage-border/50">
                      <td className="py-2 px-2 font-mono">{row.ny_date}</td>
                      <td className="py-2 px-2">{row.source_type}</td>
                      <td className="py-2 px-2 font-mono text-right">{row.risk_multiplier}</td>
                      <td className="py-2 px-2 text-vantage-muted">{row.throttle_reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {/* Allocation Drift Chart */}
      {allocationDrift.length > 0 && (
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3">Allocation Drift Over Time</h3>
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={allocationDrift}>
                <XAxis dataKey="ny_date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9ca3af" }} />
                <YAxis unit="%" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9ca3af" }} />
                <Tooltip contentStyle={CHART_TOOLTIP} />
                <Line type="monotone" dataKey="drift" stroke="#f59e0b" strokeWidth={2} dot={false} name="Drift %" />
                <Line type="monotone" dataKey="target_total" stroke="#10b981" strokeWidth={1.5} dot={false} name="Target %" />
                <Line type="monotone" dataKey="current_total" stroke="#3b82f6" strokeWidth={1.5} dot={false} name="Current %" />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Decision Pipeline */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3">Decision Pipeline</h3>
        <div className="grid grid-cols-5 gap-4 mb-4">
          {[
            { label: "Cycles", value: decisionTotals.cycles },
            { label: "Intents", value: decisionTotals.intents },
            { label: "Accepted", value: decisionTotals.accepted, color: "text-vantage-green" },
            { label: "Rejected", value: decisionTotals.rejected, color: "text-vantage-amber" },
            { label: "Gate Blocks", value: decisionTotals.gates, color: "text-vantage-red" },
          ].map((m) => (
            <div key={m.label}>
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">{m.label}</p>
              <p className={`font-mono text-lg font-bold ${m.color ?? "text-vantage-text"}`}>{m.value}</p>
            </div>
          ))}
        </div>
        {decisionPoints.length > 0 && (
          <div className="h-[280px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={decisionPoints}>
                <XAxis dataKey="ny_date" axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9ca3af" }} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 10, fill: "#9ca3af" }} />
                <Tooltip contentStyle={CHART_TOOLTIP} />
                <Bar dataKey="cycle_count" fill="#3b82f6" name="Cycles" />
                <Bar dataKey="accepted_count" fill="#10b981" name="Accepted" />
                <Bar dataKey="rejected_count" fill="#f59e0b" name="Rejected" />
                <Bar dataKey="gate_blocks" fill="#ef4444" name="Gate Blocks" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}
