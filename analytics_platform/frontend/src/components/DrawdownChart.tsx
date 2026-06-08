import { useState } from "react";
import {
  Area,
  AreaChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  ReferenceLine,
} from "recharts";

import type { DrawdownPoint } from "../types";

interface DrawdownChartProps {
  /** Strategy peak-to-current drawdown series. */
  series: DrawdownPoint[] | null | undefined;
  className?: string;
}

const TOOLTIP_STYLE = {
  backgroundColor: "#111827",
  border: "1px solid #1f2937",
  borderRadius: 6,
  fontSize: 12,
} as const;

/**
 * Drawdown-first equity chart. At age 51 the y-axis-zero-up equity curve
 * understates risk (every dip looks small against +50% absolute returns).
 * The drawdown chart puts peak-to-current loss in the foreground — which is
 * the metric that matters for sequence-of-returns risk close to retirement.
 *
 * The benchmark overlay is intentionally left out of this iteration: the
 * upstream horizon endpoint doesn't yet expose a VTTHX drawdown series.
 * Add it when the data layer ships.
 */
export function DrawdownChart({ series, className }: DrawdownChartProps) {
  const [showAnnotations] = useState(false);
  const containerClass = `bg-vantage-card border border-vantage-border rounded-lg p-4 ${className ?? ""}`;

  if (!series || series.length < 2) {
    return (
      <div className={containerClass}>
        <h3 className="text-sm font-semibold mb-2">Drawdown vs peak</h3>
        <p className="text-xs text-vantage-muted">Need 2+ account snapshots to chart drawdown.</p>
      </div>
    );
  }

  const maxDd = series.reduce((acc, p) => Math.min(acc, p.dd_pct), 0);
  const currentDd = series[series.length - 1]?.dd_pct ?? 0;

  return (
    <div className={containerClass}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold">Drawdown vs peak</h3>
        <div className="flex items-center gap-3 text-[11px] font-mono text-vantage-muted">
          <span>max <span className="text-vantage-amber font-semibold">{maxDd.toFixed(1)}%</span></span>
          <span>current <span className="text-vantage-text font-semibold">{currentDd.toFixed(1)}%</span></span>
        </div>
      </div>
      <div className="h-[260px]">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series}>
            <defs>
              <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#f59e0b" stopOpacity={0} />
                <stop offset="100%" stopColor="#f59e0b" stopOpacity={0.35} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="date"
              axisLine={false}
              tickLine={false}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              minTickGap={40}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              tick={{ fontSize: 10, fill: "#9ca3af" }}
              tickFormatter={(v: number) => `${v.toFixed(0)}%`}
              domain={[(dataMin: number) => Math.min(dataMin, -1), 0]}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(value: number) => [`${value.toFixed(2)}%`, "DD"]}
            />
            <ReferenceLine y={0} stroke="#374151" strokeDasharray="3 3" />
            {showAnnotations && (
              <ReferenceLine y={-10} stroke="#f59e0b" strokeDasharray="4 4" />
            )}
            <Area
              type="monotone"
              dataKey="dd_pct"
              stroke="#f59e0b"
              strokeWidth={1.5}
              fill="url(#ddFill)"
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
