/**
 * Scan Candidates — /scan
 * AVWAP R3K daily scan output.
 */
import { useMemo, useState } from "react";
import { ScanSearch } from "lucide-react";

import { api } from "../api";
import { StatusBadge } from "../components/Badge";
import { ScanCandidateDetailPanel } from "../components/ScanCandidateDetailPanel";
import { SkeletonCard, SkeletonTable } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { usePolling } from "../hooks/usePolling";
import type { ScanCandidate } from "../types";

type SortKey = "trend_score" | "symbol" | "entry_dist_pct" | "price" | "sector" | "avwap_slope" | "avwap_confluence" | "sector_rs";

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "\u2014";
  return Number(v).toFixed(digits);
}

export function ScanPage() {
  const [direction, setDirection] = useState("");
  const [symbol, setSymbol] = useState("");
  const [sector, setSector] = useState("");
  const [tier, setTier] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("trend_score");
  const [sortAsc, setSortAsc] = useState(false);
  const [selected, setSelected] = useState<ScanCandidate | null>(null);

  const scan = usePolling(() => api.scanCandidates({ direction: direction || undefined, symbol: symbol || undefined, sector: sector || undefined, limit: 500 }), 300_000);

  const data = scan.data?.data as any;
  const rows = (data?.rows ?? []) as ScanCandidate[];
  const latestDate = (data?.latest_date ?? null) as string | null;
  const count = (data?.count ?? 0) as number;

  const sectors = useMemo(() => {
    const s = new Set<string>();
    for (const r of rows) if (r.sector) s.add(r.sector);
    return [...s].sort();
  }, [rows]);

  const sorted = useMemo(() => {
    const copy = tier ? rows.filter((r) => r.trend_tier === tier) : [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
    return copy;
  }, [rows, sortKey, sortAsc, tier]);

  const kpis = useMemo(() => {
    const longs = rows.filter((r) => r.direction?.toLowerCase() === "long").length;
    const shorts = rows.filter((r) => r.direction?.toLowerCase() === "short").length;
    const sectorCount = new Set(rows.map((r) => r.sector).filter(Boolean)).size;
    return { total: count, longs, shorts, sectors: sectorCount };
  }, [rows, count]);

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(key === "symbol"); }
  }

  function sortHeader(label: string, key: SortKey) {
    const arrow = sortKey === key ? (sortAsc ? " \u25B4" : " \u25BE") : "";
    return (
      <th onClick={() => handleSort(key)} className="py-2 px-2 text-left text-vantage-muted font-medium whitespace-nowrap cursor-pointer hover:text-vantage-text select-none transition-colors">
        {label}{arrow}
      </th>
    );
  }

  if (scan.error) return <ErrorState message={scan.error} />;

  const isStale = latestDate && (Date.now() - new Date(latestDate).getTime()) > 2 * 86_400_000;

  return (
    <div className="p-6 space-y-4 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3">
        <ScanSearch size={24} className="text-vantage-blue" />
        <div>
          <h2 className="text-xl font-semibold">Scan Candidates</h2>
          <p className="text-[11px] text-vantage-muted">
            AVWAP R3K daily scan output
            {latestDate && <> &middot; <span className="font-mono">{latestDate}</span></>}
            {isStale && <span className="text-vantage-amber ml-2">(stale)</span>}
          </p>
        </div>
      </div>

      {/* KPIs */}
      {scan.loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">{[...Array(4)].map((_, i) => <SkeletonCard key={i} />)}</div>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Total</p>
            <p className="font-mono text-2xl font-bold">{kpis.total}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Long</p>
            <p className="font-mono text-2xl font-bold text-vantage-green">{kpis.longs}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Short</p>
            <p className="font-mono text-2xl font-bold text-vantage-red">{kpis.shorts}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Sectors</p>
            <p className="font-mono text-2xl font-bold">{kpis.sectors}</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <select value={direction} onChange={(e) => setDirection(e.target.value)} className="bg-vantage-bg border border-vantage-border rounded px-2.5 py-1.5 text-xs text-vantage-text focus:outline-none focus:border-vantage-blue/50">
          <option value="">All Directions</option>
          <option value="long">Long</option>
          <option value="short">Short</option>
        </select>
        <input placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="w-24 bg-vantage-bg border border-vantage-border rounded px-2 py-1.5 text-xs font-mono text-vantage-text focus:outline-none focus:border-vantage-blue/50" />
        <select value={tier} onChange={(e) => setTier(e.target.value)} className="bg-vantage-bg border border-vantage-border rounded px-2.5 py-1.5 text-xs text-vantage-text focus:outline-none focus:border-vantage-blue/50">
          <option value="">All Tiers</option>
          <option value="A">A</option>
          <option value="B">B</option>
        </select>
        <select value={sector} onChange={(e) => setSector(e.target.value)} className="bg-vantage-bg border border-vantage-border rounded px-2.5 py-1.5 text-xs text-vantage-text focus:outline-none focus:border-vantage-blue/50">
          <option value="">All Sectors</option>
          {sectors.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </div>

      {/* Table */}
      {scan.loading ? (
        <SkeletonTable />
      ) : (
        <div className="bg-vantage-card border border-vantage-border rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-vantage-border">
                {sortHeader("Symbol", "symbol")}
                <th className="py-2 px-2 text-left text-vantage-muted font-medium">Dir</th>
                <th className="py-2 px-2 text-left text-vantage-muted font-medium">Tier</th>
                {sortHeader("Price", "price")}
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Entry</th>
                {sortHeader("Entry%", "entry_dist_pct")}
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Stop</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">R1</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">R2</th>
                {sortHeader("Score", "trend_score")}
                {sortHeader("Slope", "avwap_slope")}
                {sortHeader("Conf.", "avwap_confluence")}
                {sortHeader("RS", "sector_rs")}
                {sortHeader("Sector", "sector")}
              </tr></thead>
              <tbody>
                {sorted.map((row, idx) => (
                  <tr key={`${row.symbol}-${idx}`} onClick={() => setSelected(row)} className={`border-b border-vantage-border/50 hover:bg-vantage-card/50 cursor-pointer ${selected?.symbol === row.symbol ? "ring-1 ring-vantage-blue/30" : ""}`}>
                    <td className="py-2 px-2 font-mono font-semibold">{row.symbol}</td>
                    <td className={`py-2 px-2 font-mono font-semibold ${row.direction?.toLowerCase() === "long" ? "text-vantage-green" : "text-vantage-red"}`}>{row.direction}</td>
                    <td className="py-2 px-2"><StatusBadge variant={row.trend_tier === "A" ? "active" : row.trend_tier === "B" ? "info" : "disabled"}>{row.trend_tier}</StatusBadge></td>
                    <td className="py-2 px-2 font-mono text-right">{fmtNum(row.price)}</td>
                    <td className="py-2 px-2 font-mono text-right">{fmtNum(row.entry_level)}</td>
                    <td className={`py-2 px-2 font-mono text-right ${row.entry_dist_pct != null ? row.entry_dist_pct <= 1.0 ? "text-vantage-green" : row.entry_dist_pct <= 3.0 ? "text-vantage-text" : "text-vantage-amber" : ""}`}>{fmtNum(row.entry_dist_pct, 1)}%</td>
                    <td className="py-2 px-2 font-mono text-right">{fmtNum(row.stop_loss)}</td>
                    <td className="py-2 px-2 font-mono text-right">{fmtNum(row.target_r1)}</td>
                    <td className="py-2 px-2 font-mono text-right">{fmtNum(row.target_r2)}</td>
                    <td className="py-2 px-2 font-mono font-semibold text-right">{fmtNum(row.trend_score, 1)}</td>
                    <td className="py-2 px-2 font-mono text-right">{fmtNum(row.avwap_slope, 3)}</td>
                    <td className={`py-2 px-2 font-mono text-right ${row.avwap_confluence != null && row.avwap_confluence >= 2 ? "text-vantage-green font-semibold" : ""}`}>{row.avwap_confluence != null ? row.avwap_confluence : "\u2014"}</td>
                    <td className={`py-2 px-2 font-mono text-right ${row.sector_rs != null ? row.sector_rs >= 1.0 ? "text-vantage-green" : "text-vantage-red" : ""}`}>{fmtNum(row.sector_rs, 3)}</td>
                    <td className="py-2 px-2 text-vantage-muted">{row.sector ?? "\u2014"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sorted.length === 0 && <EmptyState icon={ScanSearch} message="No candidates match the current filters" />}
        </div>
      )}

      {/* Detail Panel */}
      {selected && <ScanCandidateDetailPanel candidate={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
