/**
 * Trade — /trade
 * Today's RAEC coordinator trade recommendations + Schwab positions context.
 */
import {
  ArrowUpDown,
  CheckCircle,
  Clock,
  Landmark,
  ArrowUpRight,
  ArrowDownRight,
  CalendarDays,
} from "lucide-react";

import { api } from "../api";
import { StatusBadge, RegimeBadge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";
import { SkeletonTable, SkeletonCard } from "../components/Skeleton";
import { StatCard } from "../components/StatCard";
import { usePolling } from "../hooks/usePolling";
import { formatCurrency, formatPercent } from "../lib/format";
import { getMeta } from "../lib/strategies";
import type { TradeIntent, SchwabPosition } from "../types";

function todayNY(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

export function TradePage() {
  const date = todayNY();
  const trades = usePolling(() => api.todaysTrades({ date }), 30_000);

  const data = (trades.data?.data ?? {}) as Record<string, unknown>;
  const coordinator = data.coordinator as Record<string, unknown> | null;
  const events = (data.events ?? []) as Record<string, unknown>[];
  const intents = (data.intents ?? []) as TradeIntent[];
  const allocations = (data.allocations ?? []) as Record<string, unknown>[];
  const schwabAccount = data.schwab_account as Record<string, unknown> | null;
  const schwabPositions = (data.schwab_positions ?? []) as SchwabPosition[];
  const hasTrades = data.has_trades as boolean;
  const anyRebalance = data.any_rebalance as boolean;

  const loading = trades.loading;

  // Group intents by strategy
  const byStrategy: Record<string, TradeIntent[]> = {};
  for (const intent of intents) {
    (byStrategy[intent.strategy_id] ??= []).push(intent);
  }

  // Group allocations by strategy + alloc_type
  const allocByStrategy: Record<string, { target: Record<string, number>; current: Record<string, number> }> = {};
  for (const a of allocations) {
    const sid = a.strategy_id as string;
    const at = a.alloc_type as string;
    const sym = a.symbol as string;
    const wt = a.weight_pct as number;
    if (!allocByStrategy[sid]) allocByStrategy[sid] = { target: {}, current: {} };
    if (at === "target") allocByStrategy[sid].target[sym] = wt;
    else allocByStrategy[sid].current[sym] = wt;
  }

  return (
    <div className="space-y-6 max-w-[1200px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ArrowUpDown size={24} className="text-vantage-muted" />
          <div>
            <h2 className="text-xl font-semibold">Today's Trades</h2>
            <p className="text-[11px] text-vantage-muted flex items-center gap-1.5">
              <CalendarDays size={11} />
              {date} &middot; RAEC Coordinator recommendations for Schwab 401(k)
            </p>
          </div>
        </div>
      </div>

      {/* KPI Row */}
      {loading ? (
        <div className="grid grid-cols-4 gap-4">
          <SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Status"
            value={hasTrades ? "Trades Today" : "No Trades"}
          />
          <StatCard
            label="Rebalance"
            value={anyRebalance ? "Triggered" : "No Change"}
          />
          <StatCard
            label="Trade Count"
            value={String(intents.length)}
          />
          <StatCard
            label="Schwab Balance"
            value={schwabAccount ? formatCurrency(schwabAccount.total_value as number, 0) : "\u2014"}
          />
        </div>
      )}

      {/* Coordinator Summary */}
      {coordinator && (
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <CheckCircle size={14} className="text-vantage-green" />
            Coordinator Run
          </h3>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-xs">
            <div>
              <p className="text-vantage-muted mb-0.5">Capital Split</p>
              <div className="space-y-1">
                {Object.entries(coordinator.capital_split as Record<string, number>).map(([sid, pct]) => {
                  const meta = getMeta(sid);
                  return (
                    <div key={sid} className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: meta.color }} />
                      <span className="font-mono">{meta.shortName}</span>
                      <span className="text-vantage-muted">{(pct * 100).toFixed(0)}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div>
              <p className="text-vantage-muted mb-0.5">Timestamp</p>
              <p className="font-mono text-vantage-text">
                {coordinator.ts_utc ? new Date(coordinator.ts_utc as string).toLocaleTimeString() : "\u2014"}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Strategy Events */}
      {events.length > 0 && (
        <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Clock size={14} className="text-vantage-blue" />
            Strategy Evaluations
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {events.map((ev, i) => {
              const sid = ev.strategy_id as string;
              const meta = getMeta(sid);
              const shouldRebalance = ev.should_rebalance as boolean;
              return (
                <div key={i} className="rounded-lg border border-vantage-border/50 p-3" style={{ borderLeftColor: meta.color, borderLeftWidth: 3 }}>
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{meta.shortName}</span>
                      <span className="text-[10px] text-vantage-muted">{meta.subtitle}</span>
                    </div>
                    <StatusBadge variant={shouldRebalance ? "active" : "disabled"}>
                      {shouldRebalance ? "REBALANCE" : "HOLD"}
                    </StatusBadge>
                  </div>
                  <div className="flex items-center gap-3 text-xs text-vantage-muted">
                    <RegimeBadge regime={ev.regime as string} />
                    {ev.intent_count != null && (
                      <span>{ev.intent_count as number} intents</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Trade Tickets */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg">
        <div className="p-4 border-b border-vantage-border">
          <h3 className="text-sm font-semibold">Trade Tickets</h3>
          <p className="text-[10px] text-vantage-muted mt-0.5">Execute these in Schwab to align with target allocations</p>
        </div>
        {loading ? (
          <div className="p-4"><SkeletonTable /></div>
        ) : intents.length === 0 ? (
          <EmptyState icon={CheckCircle} message="No trades needed today" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-vantage-border">
                  <th className="py-2 px-3 text-left text-vantage-muted font-medium">Strategy</th>
                  <th className="py-2 px-3 text-left text-vantage-muted font-medium">Symbol</th>
                  <th className="py-2 px-3 text-left text-vantage-muted font-medium">Side</th>
                  <th className="py-2 px-3 text-right text-vantage-muted font-medium">Delta %</th>
                  <th className="py-2 px-3 text-right text-vantage-muted font-medium">Current %</th>
                  <th className="py-2 px-3 text-right text-vantage-muted font-medium">Target %</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(byStrategy).map(([sid, stratIntents]) => {
                  const meta = getMeta(sid);
                  return stratIntents.map((intent, idx) => (
                    <tr
                      key={`${sid}-${intent.symbol}`}
                      className={`border-b border-vantage-border/50 ${
                        intent.side === "BUY" ? "bg-vantage-green/[0.03]" : "bg-vantage-red/[0.03]"
                      }`}
                    >
                      {idx === 0 && (
                        <td className="py-2 px-3 font-semibold" rowSpan={stratIntents.length}>
                          <div className="flex items-center gap-2">
                            <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: meta.color }} />
                            {meta.shortName}
                          </div>
                        </td>
                      )}
                      <td className="py-2 px-3 font-mono font-semibold">{intent.symbol}</td>
                      <td className="py-2 px-3">
                        <span className={`flex items-center gap-1 font-semibold ${
                          intent.side === "BUY" ? "text-vantage-green" : "text-vantage-red"
                        }`}>
                          {intent.side === "BUY"
                            ? <ArrowUpRight size={12} />
                            : <ArrowDownRight size={12} />}
                          {intent.side}
                        </span>
                      </td>
                      <td className={`py-2 px-3 text-right font-mono ${
                        intent.delta_pct > 0 ? "text-vantage-green" : intent.delta_pct < 0 ? "text-vantage-red" : ""
                      }`}>
                        {formatPercent(intent.delta_pct, 1)}
                      </td>
                      <td className="py-2 px-3 text-right font-mono text-vantage-muted">
                        {formatPercent(intent.current_pct, 1)}
                      </td>
                      <td className="py-2 px-3 text-right font-mono font-semibold">
                        {formatPercent(intent.target_pct, 1)}
                      </td>
                    </tr>
                  ));
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Bottom row: Schwab positions + allocations */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Schwab Positions */}
        <div className="bg-vantage-card border border-vantage-border rounded-lg">
          <div className="p-4 border-b border-vantage-border">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <Landmark size={14} className="text-vantage-blue" />
              Schwab Positions
            </h3>
            {schwabAccount && (
              <p className="text-[10px] text-vantage-muted mt-0.5">
                Balance: {formatCurrency(schwabAccount.total_value as number, 0)} &middot; Cash: {formatCurrency(schwabAccount.cash as number, 0)}
              </p>
            )}
          </div>
          {loading ? (
            <div className="p-4"><SkeletonTable /></div>
          ) : schwabPositions.length === 0 ? (
            <EmptyState icon={Landmark} message="No Schwab positions" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-vantage-border">
                    <th className="py-2 px-3 text-left text-vantage-muted font-medium">Symbol</th>
                    <th className="py-2 px-3 text-right text-vantage-muted font-medium">Qty</th>
                    <th className="py-2 px-3 text-right text-vantage-muted font-medium">Value</th>
                    <th className="py-2 px-3 text-right text-vantage-muted font-medium">Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {schwabPositions.map((pos) => (
                    <tr key={pos.symbol} className="border-b border-vantage-border/50">
                      <td className="py-2 px-3 font-mono font-semibold">{pos.symbol}</td>
                      <td className="py-2 px-3 text-right font-mono">{pos.qty}</td>
                      <td className="py-2 px-3 text-right font-mono">{formatCurrency(pos.market_value, 0)}</td>
                      <td className="py-2 px-3 text-right font-mono text-vantage-muted">
                        {pos.weight_pct != null ? `${pos.weight_pct.toFixed(1)}%` : "\u2014"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Target Allocations */}
        <div className="bg-vantage-card border border-vantage-border rounded-lg">
          <div className="p-4 border-b border-vantage-border">
            <h3 className="text-sm font-semibold">Target Allocations</h3>
            <p className="text-[10px] text-vantage-muted mt-0.5">Current vs target weight per strategy</p>
          </div>
          {loading ? (
            <div className="p-4"><SkeletonTable /></div>
          ) : Object.keys(allocByStrategy).length === 0 ? (
            <EmptyState message="No allocation data for today" />
          ) : (
            <div className="p-4 space-y-4">
              {Object.entries(allocByStrategy).map(([sid, { target, current }]) => {
                const meta = getMeta(sid);
                const allSymbols = [...new Set([...Object.keys(target), ...Object.keys(current)])].sort();
                return (
                  <div key={sid}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: meta.color }} />
                      <span className="text-xs font-semibold">{meta.shortName}</span>
                      <span className="text-[10px] text-vantage-muted">{meta.subtitle}</span>
                    </div>
                    <div className="space-y-1.5">
                      {allSymbols.map((sym) => {
                        const tgt = target[sym] ?? 0;
                        const cur = current[sym] ?? 0;
                        const maxW = Math.max(tgt, cur, 1);
                        return (
                          <div key={sym} className="flex items-center gap-2 text-xs">
                            <span className="w-12 font-mono text-[10px]">{sym}</span>
                            <div className="flex-1 h-4 bg-vantage-border/30 rounded overflow-hidden relative">
                              {/* Current */}
                              <div
                                className="absolute inset-y-0 left-0 bg-vantage-muted/30 rounded-l"
                                style={{ width: `${(cur / maxW) * 100}%` }}
                              />
                              {/* Target */}
                              <div
                                className="absolute inset-y-0 left-0 rounded-l"
                                style={{
                                  width: `${(tgt / maxW) * 100}%`,
                                  backgroundColor: `${meta.color}40`,
                                  borderRight: `2px solid ${meta.color}`,
                                }}
                              />
                            </div>
                            <span className="w-16 text-right font-mono text-[10px] text-vantage-muted">
                              {cur.toFixed(1)}% &rarr; {tgt.toFixed(1)}%
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
              <div className="flex items-center gap-4 text-[10px] text-vantage-muted pt-2 border-t border-vantage-border/50">
                <span className="flex items-center gap-1"><span className="w-3 h-2 bg-vantage-muted/30 rounded" /> Current</span>
                <span className="flex items-center gap-1"><span className="w-3 h-2 bg-vantage-blue/40 rounded border-r-2 border-vantage-blue" /> Target</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
