/**
 * Schwab Account — /ops/schwab
 * Live 401(k) positions, balances, and reconciliation.
 */
import { Landmark, AlertTriangle } from "lucide-react";

import { api } from "../api";
import { StatusBadge } from "../components/Badge";
import { SkeletonCard, SkeletonTable } from "../components/Skeleton";
import { usePolling } from "../hooks/usePolling";
import { formatCurrency, formatPercent } from "../lib/format";
import type { SchwabAccountBalance, SchwabPosition, SchwabOrder, SchwabReconciliation } from "../types";

export function SchwabAccountPage() {
  const poll = usePolling(() => api.schwabOverview(), 60_000);
  const data = poll.data?.data as Record<string, unknown> | undefined;

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
              </tr></thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.symbol} className="border-b border-vantage-border/50">
                    <td className="py-2 px-2 font-mono font-semibold">{p.symbol}</td>
                    <td className="py-2 px-2 font-mono text-right">{p.qty?.toLocaleString() ?? "\u2014"}</td>
                    <td className="py-2 px-2 font-mono text-right">{formatCurrency(p.market_value)}</td>
                    <td className="py-2 px-2 font-mono text-right">{formatPercent(p.weight_pct, 1)}</td>
                    <td className="py-2 px-2 font-mono text-right">{formatCurrency(p.cost_basis)}</td>
                  </tr>
                ))}
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
