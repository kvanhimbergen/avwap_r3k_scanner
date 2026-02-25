/**
 * ScanCandidateDetailPanel — Slide-out detail panel for scan candidates.
 * Shows full setup context: price levels, AVWAP/VWAP states, extension, structure.
 */
import { useEffect, useState } from "react";
import { ExternalLink, X } from "lucide-react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { StatusBadge } from "./Badge";
import { CandlestickChart, type CandlePoint, type LinePoint, type PriceLevel } from "./CandlestickChart";
import type { ScanCandidate } from "../types";

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "\u2014";
  return Number(v).toFixed(digits);
}

type ContextBadgeVariant = "active" | "warning" | "error" | "disabled";

function contextVariant(state: string | null): ContextBadgeVariant {
  if (!state || state === "none" || state === "neutral") return "disabled";
  const s = state.toLowerCase();
  if (s === "bullish" || s === "above" || s === "accepted" || s === "balanced" || s === "reclaimed") return "active";
  if (s === "bearish" || s === "below" || s === "extended" || s === "rejected") return "error";
  if (s === "moderate" || s === "inside" || s === "testing") return "warning";
  return "disabled";
}

function ContextBadge({ label, state }: { label: string; state: string | null }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-[10px] text-vantage-muted uppercase tracking-wide">{label}</span>
      <StatusBadge variant={contextVariant(state)}>{state ?? "\u2014"}</StatusBadge>
    </div>
  );
}

function LevelRow({ label, value, color }: { label: string; value: number | null; color?: string }) {
  return (
    <div className="flex items-center justify-between py-1">
      <span className="text-[10px] text-vantage-muted uppercase tracking-wide">{label}</span>
      <span className={`font-mono text-xs font-semibold ${color ?? "text-vantage-text"}`}>
        ${fmtNum(value)}
      </span>
    </div>
  );
}

export function ScanCandidateDetailPanel({ candidate, onClose }: { candidate: ScanCandidate; onClose: () => void }) {
  const entry = candidate.entry_level ?? 0;
  const stop = candidate.stop_loss ?? 0;
  const r1 = candidate.target_r1 ?? 0;
  const r2 = candidate.target_r2 ?? 0;
  const risk = entry - stop;
  const reward = r2 - entry;
  const rr = risk > 0 ? reward / risk : 0;

  // Chart data
  const [chartCandles, setChartCandles] = useState<CandlePoint[]>([]);
  const [chartAvwap, setChartAvwap] = useState<LinePoint[]>([]);

  useEffect(() => {
    let cancelled = false;
    api.scanChartData(candidate.symbol, candidate.anchor).then((res) => {
      if (cancelled) return;
      const d = res.data as { candles?: CandlePoint[]; avwap?: LinePoint[] };
      setChartCandles(d.candles ?? []);
      setChartAvwap(d.avwap ?? []);
    }).catch(() => {
      if (!cancelled) { setChartCandles([]); setChartAvwap([]); }
    });
    return () => { cancelled = true; };
  }, [candidate.symbol, candidate.anchor]);

  const chartLevels: PriceLevel[] = [
    ...(entry > 0 ? [{ price: entry, color: "#3b82f6", label: "Entry" }] : []),
    ...(stop > 0 ? [{ price: stop, color: "#ef4444", label: "Stop" }] : []),
    ...(r1 > 0 ? [{ price: r1, color: "#22c55e", label: "R1" }] : []),
    ...(r2 > 0 ? [{ price: r2, color: "#22c55e", label: "R2" }] : []),
  ];

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />

      {/* Panel */}
      <div className="fixed inset-y-0 right-0 w-[480px] bg-vantage-card border-l border-vantage-border z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="shrink-0 p-4 border-b border-vantage-border flex items-center justify-between">
          <div className="flex items-center gap-3">
            <a
              href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(candidate.symbol)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="font-mono text-xl font-bold hover:text-vantage-blue transition-colors flex items-center gap-1.5"
              title="Open in TradingView"
            >
              {candidate.symbol}
              <ExternalLink size={14} className="text-vantage-muted" />
            </a>
            <StatusBadge variant={candidate.direction?.toLowerCase() === "long" ? "active" : "error"}>
              {candidate.direction}
            </StatusBadge>
            <StatusBadge variant={candidate.trend_tier === "A" ? "active" : candidate.trend_tier === "B" ? "info" : "disabled"}>
              Tier {candidate.trend_tier}
            </StatusBadge>
          </div>
          <button className="p-1 hover:bg-vantage-border rounded transition-colors" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Sector + Anchor */}
          <div className="flex items-center gap-4">
            {candidate.sector && (
              <div>
                <span className="text-[10px] text-vantage-muted uppercase tracking-wide">Sector</span>
                <p className="text-xs font-medium">{candidate.sector}</p>
              </div>
            )}
            {candidate.anchor && (
              <div>
                <span className="text-[10px] text-vantage-muted uppercase tracking-wide">Anchor</span>
                <p className="text-xs font-medium font-mono">{candidate.anchor}</p>
              </div>
            )}
            {candidate.sector_rs != null && (
              <div>
                <span className="text-[10px] text-vantage-muted uppercase tracking-wide">Sector RS</span>
                <p className={`text-xs font-medium font-mono ${candidate.sector_rs >= 1.0 ? "text-vantage-green" : "text-vantage-red"}`}>{fmtNum(candidate.sector_rs, 3)}</p>
              </div>
            )}
          </div>

          {/* Price Levels */}
          <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
            <p className="text-[10px] text-vantage-muted uppercase tracking-wide mb-2 font-semibold">Price Levels</p>
            <LevelRow label="Price" value={candidate.price} />
            <LevelRow label="Entry" value={candidate.entry_level} color="text-vantage-blue" />
            <LevelRow label="Stop" value={candidate.stop_loss} color="text-vantage-red" />
            <LevelRow label="Target R1" value={candidate.target_r1} color="text-vantage-green" />
            <LevelRow label="Target R2" value={candidate.target_r2} color="text-vantage-green" />
            <div className="border-t border-vantage-border/50 mt-2 pt-2 grid grid-cols-3 gap-2">
              <div>
                <span className="text-[9px] text-vantage-muted uppercase">Risk</span>
                <p className="font-mono text-xs font-semibold text-vantage-red">${fmtNum(risk)}</p>
              </div>
              <div>
                <span className="text-[9px] text-vantage-muted uppercase">Reward</span>
                <p className="font-mono text-xs font-semibold text-vantage-green">${fmtNum(reward)}</p>
              </div>
              <div>
                <span className="text-[9px] text-vantage-muted uppercase">R:R</span>
                <p className="font-mono text-xs font-semibold">{fmtNum(rr, 1)}:1</p>
              </div>
            </div>
          </div>

          {/* Chart */}
          <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide font-semibold">Chart (90d)</p>
              <a
                href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(candidate.symbol)}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[10px] text-vantage-muted hover:text-vantage-blue transition-colors flex items-center gap-1"
              >
                TradingView <ExternalLink size={10} />
              </a>
            </div>
            <CandlestickChart candles={chartCandles} avwap={chartAvwap} levels={chartLevels} height={280} />
          </div>

          {/* Scores */}
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">TrendScore</p>
              <p className="font-mono text-lg font-bold">{fmtNum(candidate.trend_score, 1)}</p>
            </div>
            <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Entry%</p>
              <p className="font-mono text-lg font-bold">{fmtNum(candidate.entry_dist_pct, 1)}%</p>
            </div>
            <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">AVWAP Slope</p>
              <p className="font-mono text-lg font-bold">{fmtNum(candidate.avwap_slope, 3)}</p>
            </div>
            <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Confluence</p>
              <p className={`font-mono text-lg font-bold ${candidate.avwap_confluence != null && candidate.avwap_confluence >= 2 ? "text-vantage-green" : ""}`}>{candidate.avwap_confluence ?? "\u2014"}</p>
            </div>
          </div>

          {/* AVWAP Context */}
          <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
            <p className="text-[10px] text-vantage-muted uppercase tracking-wide mb-2 font-semibold">AVWAP Context</p>
            <ContextBadge label="Control" state={candidate.setup_avwap_control} />
            <ContextBadge label="Reclaim" state={candidate.setup_avwap_reclaim} />
            <ContextBadge label="Acceptance" state={candidate.setup_avwap_acceptance} />
            {candidate.setup_avwap_dist_pct != null && (
              <div className="flex items-center justify-between py-1">
                <span className="text-[10px] text-vantage-muted uppercase tracking-wide">Distance</span>
                <span className="font-mono text-xs">{fmtNum(candidate.setup_avwap_dist_pct, 2)}%</span>
              </div>
            )}
          </div>

          {/* VWAP Context */}
          <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
            <p className="text-[10px] text-vantage-muted uppercase tracking-wide mb-2 font-semibold">VWAP Context</p>
            <ContextBadge label="Control" state={candidate.setup_vwap_control} />
            <ContextBadge label="Reclaim" state={candidate.setup_vwap_reclaim} />
            <ContextBadge label="Acceptance" state={candidate.setup_vwap_acceptance} />
            {candidate.setup_vwap_dist_pct != null && (
              <div className="flex items-center justify-between py-1">
                <span className="text-[10px] text-vantage-muted uppercase tracking-wide">Distance</span>
                <span className="font-mono text-xs">{fmtNum(candidate.setup_vwap_dist_pct, 2)}%</span>
              </div>
            )}
          </div>

          {/* Extension & Structure */}
          <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
            <p className="text-[10px] text-vantage-muted uppercase tracking-wide mb-2 font-semibold">Extension & Structure</p>
            <ContextBadge label="Extension" state={candidate.setup_extension_state} />
            <ContextBadge label="Gap Reset" state={candidate.setup_gap_reset} />
            <ContextBadge label="Structure" state={candidate.setup_structure_state} />
          </div>

          {/* Log Trade Link */}
          <Link
            to={`/trade-log?symbol=${encodeURIComponent(candidate.symbol)}&direction=${encodeURIComponent(candidate.direction ?? "long")}&entry_price=${candidate.entry_level ?? ""}&stop_loss=${candidate.stop_loss ?? ""}&target_r1=${candidate.target_r1 ?? ""}&target_r2=${candidate.target_r2 ?? ""}&strategy_source=AVWAP_SCAN`}
            className="block w-full text-center py-2 bg-vantage-blue text-white text-xs font-medium rounded hover:bg-vantage-blue/80 transition-colors"
            onClick={onClose}
          >
            Log Trade
          </Link>
        </div>
      </div>
    </>
  );
}
