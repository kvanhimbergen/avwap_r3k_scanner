/**
 * Rebalance Dashboard — /ops/rebalance
 * Current positions vs combined targets with trade recommendations.
 */
import { Scale } from "lucide-react";

import { api } from "../api";
import { RegimeBadge, StatusBadge } from "../components/Badge";
import { SkeletonCard, SkeletonTable } from "../components/Skeleton";
import { usePolling } from "../hooks/usePolling";
import { formatCurrency, formatPercent } from "../lib/format";
import { getMeta, regimeColor } from "../lib/strategies";
import type { RebalanceDashboardData, RebalanceStrategySlice, RebalanceTrade } from "../types";

export function RebalancePage() {
  const poll = usePolling(() => api.rebalanceDashboard(), 60_000);
  const data = poll.data?.data as RebalanceDashboardData | undefined;

  const actionableCount = data?.trades.filter((t) => t.actionable).length ?? 0;

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Scale size={24} className="text-vantage-blue" />
        <div>
          <h2 className="text-xl font-semibold">Rebalance Dashboard</h2>
          <p className="text-[11px] text-vantage-muted">
            Combined V3/V4/V5 targets vs current positions with trade recommendations
          </p>
        </div>
      </div>

      {/* KPI row */}
      {poll.loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : data ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KpiCard label="Portfolio Value" value={formatCurrency(data.portfolio_value, 0)} />
          <KpiCard label="Positions Date" value={data.positions_date ?? "\u2014"} />
          <KpiCard
            label="Token Expiry"
            value={data.token_health.healthy ? `${data.token_health.days_until_expiry}d` : "Expired"}
            alert={!data.token_health.healthy}
          />
          <KpiCard
            label="Trades Needed"
            value={String(actionableCount)}
            alert={actionableCount > 0}
          />
        </div>
      ) : null}

      {/* Strategy cards */}
      {poll.loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <SkeletonCard key={i} />
          ))}
        </div>
      ) : data ? (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {data.strategies.map((s) => (
            <StrategyCard key={s.id} strategy={s} />
          ))}
        </div>
      ) : null}

      {/* Trade recommendations */}
      {poll.loading ? (
        <SkeletonTable />
      ) : data && data.trades.length > 0 ? (
        <TradeTable trades={data.trades} portfolioValue={data.portfolio_value} />
      ) : data ? (
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-6 text-center text-vantage-muted text-sm">
          No trade recommendations — portfolio is aligned with targets.
        </div>
      ) : null}

      {/* Error state */}
      {poll.error && (
        <div className="bg-vantage-red/10 border border-vantage-red/30 rounded-lg p-4 text-sm text-vantage-red">
          {poll.error}
        </div>
      )}
    </div>
  );
}

/* ── KPI Card ─────────────────────────────────────────────── */

function KpiCard({ label, value, alert }: { label: string; value: string; alert?: boolean }) {
  return (
    <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
      <p className="text-[11px] text-vantage-muted uppercase tracking-wide">{label}</p>
      <p className={`font-mono text-lg font-semibold mt-1 ${alert ? "text-vantage-amber" : ""}`}>
        {value}
      </p>
    </div>
  );
}

/* ── Strategy Card ────────────────────────────────────────── */

function StrategyCard({ strategy }: { strategy: RebalanceStrategySlice }) {
  const meta = getMeta(strategy.id);
  const targets = Object.entries(strategy.targets).sort(([, a], [, b]) => b - a);

  return (
    <div
      className="bg-vantage-card border border-vantage-border rounded-lg p-4"
      style={{ borderLeftColor: meta.color, borderLeftWidth: 3 }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-sm" style={{ color: meta.color }}>
            {meta.shortName}
          </span>
          <span className="text-[11px] text-vantage-muted">{meta.subtitle}</span>
          <span className="text-[10px] text-vantage-muted font-mono">
            ({(strategy.weight * 100).toFixed(0)}%)
          </span>
        </div>
        <RegimeBadge regime={strategy.smoothed_regime} />
      </div>

      {/* Regime mismatch indicator */}
      {strategy.regime && strategy.smoothed_regime && strategy.regime !== strategy.smoothed_regime && (
        <div className="text-[10px] text-vantage-amber mb-2">
          Raw: {strategy.regime} (smoothing to {strategy.smoothed_regime})
        </div>
      )}

      {/* Targets */}
      <div className="space-y-1 mb-3">
        {targets.map(([sym, pct]) => (
          <div key={sym} className="flex justify-between text-xs">
            <span className="font-mono">{sym}</span>
            <span className="text-vantage-muted">{pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>

      {/* Footer: last rebalance + cooldown */}
      <div className="flex items-center justify-between text-[10px] text-vantage-muted border-t border-vantage-border pt-2">
        <span>
          Last rebal: {strategy.last_rebalance_date ?? "\u2014"}
        </span>
        {strategy.cooldown_days_remaining > 0 ? (
          <StatusBadge variant="warning">
            COOLDOWN {strategy.cooldown_days_remaining}d
          </StatusBadge>
        ) : (
          <StatusBadge variant="active">READY</StatusBadge>
        )}
      </div>
    </div>
  );
}

/* ── Trade Recommendations Table ──────────────────────────── */

function TradeTable({ trades, portfolioValue }: { trades: RebalanceTrade[]; portfolioValue: number | null }) {
  return (
    <div className="bg-vantage-card border border-vantage-border rounded-lg overflow-hidden">
      <div className="px-4 py-3 border-b border-vantage-border flex items-center justify-between">
        <h3 className="text-sm font-semibold">Trade Recommendations</h3>
        {portfolioValue != null && (
          <span className="text-[11px] text-vantage-muted">
            Threshold: {formatCurrency(Math.max(250, portfolioValue * 0.005), 0)}
          </span>
        )}
      </div>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-vantage-border text-vantage-muted text-left">
            <th className="px-4 py-2 font-medium">Symbol</th>
            <th className="px-4 py-2 font-medium">Side</th>
            <th className="px-4 py-2 font-medium text-right">Current %</th>
            <th className="px-4 py-2 font-medium text-right">Target %</th>
            <th className="px-4 py-2 font-medium text-right">Delta %</th>
            <th className="px-4 py-2 font-medium text-right">$ Amount</th>
            <th className="px-4 py-2 font-medium text-center">Status</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t) => (
            <tr
              key={t.symbol}
              className={`border-b border-vantage-border/50 ${
                !t.actionable ? "opacity-40" : ""
              } ${
                t.side === "BUY"
                  ? "bg-vantage-green/[0.03]"
                  : "bg-vantage-red/[0.03]"
              }`}
            >
              <td className="px-4 py-2 font-mono font-medium">{t.symbol}</td>
              <td className="px-4 py-2">
                <span
                  className={`font-semibold ${
                    t.side === "BUY" ? "text-vantage-green" : "text-vantage-red"
                  }`}
                >
                  {t.side}
                </span>
              </td>
              <td className="px-4 py-2 text-right font-mono">{t.current_pct.toFixed(1)}%</td>
              <td className="px-4 py-2 text-right font-mono">{t.target_pct.toFixed(1)}%</td>
              <td className="px-4 py-2 text-right font-mono">
                <span className={t.delta_pct > 0 ? "text-vantage-green" : "text-vantage-red"}>
                  {formatPercent(t.delta_pct, 1)}
                </span>
              </td>
              <td className="px-4 py-2 text-right font-mono">{formatCurrency(t.dollar_amount, 0)}</td>
              <td className="px-4 py-2 text-center">
                {t.actionable ? (
                  <StatusBadge variant="active">ACTION</StatusBadge>
                ) : (
                  <StatusBadge variant="disabled">SKIP</StatusBadge>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
