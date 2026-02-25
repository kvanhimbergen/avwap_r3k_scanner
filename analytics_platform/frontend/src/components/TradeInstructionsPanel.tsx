/**
 * Trade Instructions Panel — shows RAEC V3/V4/V5 rebalance intents
 * with dollar amounts, actionability threshold, and strategy grouping.
 */
import { ArrowUpRight, ArrowDownRight, CheckCircle } from "lucide-react";

import { StatusBadge, RegimeBadge } from "./Badge";
import { EmptyState } from "./EmptyState";
import { formatCurrency, formatPercent } from "../lib/format";
import { getMeta } from "../lib/strategies";
import type {
  TradeInstructionsPayload,
  TradeInstructionDay,
  TradeInstruction,
  TradeInstructionEvent,
} from "../types";

function todayNY(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: "America/New_York" });
}

function IntentRow({ intent, actionable }: { intent: TradeInstruction; actionable: boolean }) {
  const isBuy = intent.side === "BUY";
  return (
    <tr
      className={`border-b border-vantage-border/50 ${
        !actionable
          ? "opacity-40"
          : isBuy
            ? "bg-vantage-green/[0.03]"
            : "bg-vantage-red/[0.03]"
      }`}
    >
      <td className="py-1.5 px-2 font-mono font-semibold text-xs">{intent.symbol}</td>
      <td className="py-1.5 px-2 text-xs">
        <span className={`flex items-center gap-1 font-semibold ${isBuy ? "text-vantage-green" : "text-vantage-red"}`}>
          {isBuy ? <ArrowUpRight size={11} /> : <ArrowDownRight size={11} />}
          {intent.side}
        </span>
      </td>
      <td className={`py-1.5 px-2 text-right font-mono text-xs ${intent.delta_pct > 0 ? "text-vantage-green" : intent.delta_pct < 0 ? "text-vantage-red" : ""}`}>
        {formatPercent(intent.delta_pct, 1)}
      </td>
      <td className={`py-1.5 px-2 text-right font-mono text-xs ${!actionable ? "" : isBuy ? "text-vantage-green" : "text-vantage-red"}`}>
        {formatCurrency(intent.dollar_amount, 0)}
        {!actionable && <span className="ml-1 text-[9px] text-vantage-muted">(skip)</span>}
      </td>
      <td className="py-1.5 px-2 text-right font-mono text-xs text-vantage-muted">{formatPercent(intent.current_pct, 1)}</td>
      <td className="py-1.5 px-2 text-right font-mono text-xs font-semibold">{formatPercent(intent.target_pct, 1)}</td>
    </tr>
  );
}

function StrategyBlock({ strategyId, intents, event }: {
  strategyId: string;
  intents: TradeInstruction[];
  event: TradeInstructionEvent | undefined;
}) {
  const meta = getMeta(strategyId);
  const shouldRebalance = event?.should_rebalance ?? false;

  return (
    <div className="rounded-lg border border-vantage-border/50 overflow-hidden" style={{ borderLeftColor: meta.color, borderLeftWidth: 3 }}>
      <div className="flex items-center justify-between px-3 py-2 bg-vantage-bg/50">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-xs">{meta.shortName}</span>
          <span className="text-[10px] text-vantage-muted">{meta.subtitle}</span>
          {event && <RegimeBadge regime={event.regime} />}
        </div>
        <StatusBadge variant={shouldRebalance ? "active" : "disabled"}>
          {shouldRebalance ? "REBALANCE" : "HOLD"}
        </StatusBadge>
      </div>
      {intents.length > 0 ? (
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-vantage-border/50">
              <th className="py-1 px-2 text-left text-vantage-muted font-medium">Symbol</th>
              <th className="py-1 px-2 text-left text-vantage-muted font-medium">Side</th>
              <th className="py-1 px-2 text-right text-vantage-muted font-medium">Delta</th>
              <th className="py-1 px-2 text-right text-vantage-muted font-medium">Amount</th>
              <th className="py-1 px-2 text-right text-vantage-muted font-medium">Current</th>
              <th className="py-1 px-2 text-right text-vantage-muted font-medium">Target</th>
            </tr>
          </thead>
          <tbody>
            {intents.map((intent) => (
              <IntentRow key={intent.intent_id} intent={intent} actionable={intent.actionable} />
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-[10px] text-vantage-muted px-3 py-2">No intents</p>
      )}
    </div>
  );
}

function DaySection({ day, isToday }: { day: TradeInstructionDay; isToday: boolean }) {
  // Group intents by strategy
  const byStrategy: Record<string, TradeInstruction[]> = {};
  for (const intent of day.intents) {
    (byStrategy[intent.strategy_id] ??= []).push(intent);
  }
  // Event map
  const eventMap: Record<string, TradeInstructionEvent> = {};
  for (const ev of day.events) {
    eventMap[ev.strategy_id] = ev;
  }
  // Ensure all strategies from events appear even if no intents
  for (const ev of day.events) {
    if (!byStrategy[ev.strategy_id]) byStrategy[ev.strategy_id] = [];
  }

  const strategyIds = Object.keys(byStrategy).sort();

  return (
    <div className={!isToday ? "opacity-50" : ""}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-semibold font-mono">{day.ny_date}</span>
        {isToday && <StatusBadge variant="info">TODAY</StatusBadge>}
        {day.actionable_count > 0 && (
          <StatusBadge variant="warning">{day.actionable_count} actionable</StatusBadge>
        )}
      </div>
      <div className="space-y-2">
        {strategyIds.map((sid) => (
          <StrategyBlock
            key={sid}
            strategyId={sid}
            intents={byStrategy[sid]}
            event={eventMap[sid]}
          />
        ))}
      </div>
    </div>
  );
}

export function TradeInstructionsPanel({ data }: { data: TradeInstructionsPayload }) {
  const today = todayNY();
  const totalActionable = data.days.reduce((sum, d) => sum + d.actionable_count, 0);
  const allHold = data.days.length > 0 && data.days.every((d) =>
    d.events.every((e) => !e.should_rebalance) && d.intents.length === 0
  );

  return (
    <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold">Trade Instructions</h3>
          {data.total_value != null && (
            <span className="text-[10px] text-vantage-muted font-mono">
              Portfolio: {formatCurrency(data.total_value, 0)}
            </span>
          )}
          {totalActionable > 0 && (
            <StatusBadge variant="warning">{totalActionable} actionable</StatusBadge>
          )}
          {allHold && (
            <StatusBadge variant="active">NO TRADES NEEDED</StatusBadge>
          )}
        </div>
      </div>

      {/* Threshold note */}
      {data.threshold_dollars > 0 && (
        <p className="text-[10px] text-vantage-muted mb-3">
          Trades below {formatCurrency(data.threshold_dollars, 0)} ({data.threshold_pct}% of portfolio) are dimmed
        </p>
      )}

      {/* Days */}
      {data.days.length === 0 ? (
        <EmptyState icon={CheckCircle} message="No trade data in the last 3 days" />
      ) : (
        <div className="space-y-4">
          {data.days.map((day) => (
            <DaySection key={day.ny_date} day={day} isToday={day.ny_date === today} />
          ))}
        </div>
      )}
    </div>
  );
}
