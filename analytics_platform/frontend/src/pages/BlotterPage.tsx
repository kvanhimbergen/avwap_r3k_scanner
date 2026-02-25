/**
 * Blotter — /blotter
 * Unified trade journal across all strategies and books.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ScrollText, Download } from "lucide-react";

import { api } from "../api";
import { SkeletonCard, SkeletonTable } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { usePolling } from "../hooks/usePolling";
import { bookFromId, getMeta } from "../lib/strategies";

const ALL_STRATEGIES = [
  { id: "", label: "All Strategies" },
  { id: "S1_AVWAP_CORE", label: "S1 AVWAP" },
  { id: "S2_LETF_ORB_AGGRO", label: "S2 LETF ORB" },
  { id: "RAEC_401K_V1", label: "V1 Core" },
  { id: "RAEC_401K_V2", label: "V2 Enhanced" },
  { id: "RAEC_401K_V3", label: "V3 Aggressive" },
  { id: "RAEC_401K_V4", label: "V4 Macro" },
  { id: "RAEC_401K_V5", label: "V5 AI/Tech" },
  { id: "RAEC_401K_COORD", label: "Coordinator" },
];

const DATE_PRESETS = [
  { id: "", label: "All Time" },
  { id: "1", label: "Today" },
  { id: "7", label: "7d" },
  { id: "30", label: "30d" },
];

type SortKey = "ny_date" | "strategy_id" | "symbol" | "side" | "delta_pct";

function daysAgoStr(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

export function BlotterPage() {
  const [strategyId, setStrategyId] = useState("");
  const [bookFilter, setBookFilter] = useState("");
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState("");
  const [datePreset, setDatePreset] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("ny_date");
  const [sortAsc, setSortAsc] = useState(false);

  const startDate = useMemo(() => {
    if (!datePreset) return undefined;
    return daysAgoStr(Number(datePreset));
  }, [datePreset]);

  const journal = usePolling(
    () => api.journal({ strategy_id: strategyId || undefined, symbol: symbol || undefined, side: side || undefined, start: startDate, limit: 500 }),
    45_000,
  );

  const rows = ((journal.data?.data as any)?.rows ?? []) as any[];

  const bookFiltered = useMemo(() => {
    if (!bookFilter) return rows;
    return rows.filter((r: any) => bookFromId(r.strategy_id ?? "") === bookFilter);
  }, [rows, bookFilter]);

  const sorted = useMemo(() => {
    const copy = [...bookFiltered];
    copy.sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
    return copy;
  }, [bookFiltered, sortKey, sortAsc]);

  const kpis = useMemo(() => {
    const buys = bookFiltered.filter((r: any) => r.side === "BUY").length;
    const sells = bookFiltered.filter((r: any) => r.side === "SELL").length;
    const symbols = new Set(bookFiltered.map((r: any) => r.symbol)).size;
    return { total: bookFiltered.length, buys, sells, symbols };
  }, [bookFiltered]);

  function handleSort(key: SortKey) {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(true); }
  }

  function sortHeader(label: string, key: SortKey) {
    const arrow = sortKey === key ? (sortAsc ? " \u25B4" : " \u25BE") : "";
    return (
      <th
        onClick={() => handleSort(key)}
        className="py-2 px-2 text-left text-vantage-muted font-medium whitespace-nowrap cursor-pointer hover:text-vantage-text select-none transition-colors"
      >
        {label}{arrow}
      </th>
    );
  }

  function handleExportCsv() {
    if (sorted.length === 0) return;
    const headers = ["Date", "Book", "Strategy", "Symbol", "Side", "Delta%", "Target%", "Current%", "Regime", "Posted"];
    const csvRows = sorted.map((row: any) => [
      row.ny_date, bookFromId(row.strategy_id ?? ""), row.strategy_id, row.symbol, row.side,
      row.delta_pct != null ? Number(row.delta_pct).toFixed(1) : "",
      row.target_pct != null ? Number(row.target_pct).toFixed(1) : "",
      row.current_pct != null ? Number(row.current_pct).toFixed(1) : "",
      row.regime ?? "", row.posted == null ? "" : row.posted ? "Yes" : "No",
    ]);
    const csv = [headers.join(","), ...csvRows.map((r: string[]) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `blotter-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (journal.error) return <ErrorState message={journal.error} />;

  return (
    <div className="p-6 space-y-4 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ScrollText size={24} className="text-vantage-blue" />
          <div>
            <h2 className="text-xl font-semibold">Blotter</h2>
            <p className="text-[11px] text-vantage-muted">Unified trade journal across all strategies</p>
          </div>
        </div>
        <button
          onClick={handleExportCsv}
          disabled={sorted.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-vantage-card border border-vantage-border rounded-lg hover:border-vantage-blue/50 transition-colors text-vantage-text disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Download size={12} /> Export CSV
        </button>
      </div>

      {/* Summary stats */}
      {journal.loading ? (
        <div className="grid grid-cols-4 gap-4"><SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard /></div>
      ) : (
        <div className="grid grid-cols-4 gap-4">
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Total Trades</p>
            <p className="font-mono text-2xl font-bold">{kpis.total}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Buys</p>
            <p className="font-mono text-2xl font-bold text-vantage-green">{kpis.buys}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Sells</p>
            <p className="font-mono text-2xl font-bold text-vantage-red">{kpis.sells}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Unique Symbols</p>
            <p className="font-mono text-2xl font-bold">{kpis.symbols}</p>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <select value={bookFilter} onChange={(e) => setBookFilter(e.target.value)} className="bg-vantage-bg border border-vantage-border rounded px-2.5 py-1.5 text-xs text-vantage-text focus:outline-none focus:border-vantage-blue/50 appearance-none cursor-pointer pr-6">
          <option value="">All Books</option>
          <option value="alpaca">Alpaca Paper</option>
          <option value="schwab">Schwab 401K</option>
        </select>
        <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)} className="bg-vantage-bg border border-vantage-border rounded px-2.5 py-1.5 text-xs text-vantage-text focus:outline-none focus:border-vantage-blue/50 appearance-none cursor-pointer pr-6">
          {ALL_STRATEGIES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </select>
        <input placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} className="w-24 bg-vantage-bg border border-vantage-border rounded px-2 py-1.5 text-xs font-mono text-vantage-text focus:outline-none focus:border-vantage-blue/50" />
        <select value={side} onChange={(e) => setSide(e.target.value)} className="bg-vantage-bg border border-vantage-border rounded px-2.5 py-1.5 text-xs text-vantage-text focus:outline-none focus:border-vantage-blue/50 appearance-none cursor-pointer pr-6">
          <option value="">All Sides</option>
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
        <div className="flex items-center gap-1">
          {DATE_PRESETS.map((p) => (
            <button key={p.id} onClick={() => setDatePreset(p.id)} className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${datePreset === p.id ? "bg-vantage-border text-vantage-text" : "text-vantage-muted hover:text-vantage-text"}`}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      {journal.loading ? (
        <SkeletonTable />
      ) : (
        <div className="bg-vantage-card border border-vantage-border rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-vantage-border">
                  {sortHeader("Date", "ny_date")}
                  <th className="py-2 px-2 text-left text-vantage-muted font-medium">Book</th>
                  {sortHeader("Strategy", "strategy_id")}
                  {sortHeader("Symbol", "symbol")}
                  {sortHeader("Side", "side")}
                  {sortHeader("Delta%", "delta_pct")}
                  <th className="py-2 px-2 text-right text-vantage-muted font-medium">Target%</th>
                  <th className="py-2 px-2 text-right text-vantage-muted font-medium">Current%</th>
                  <th className="py-2 px-2 text-left text-vantage-muted font-medium">Regime</th>
                  <th className="py-2 px-2 text-center text-vantage-muted font-medium">Posted</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((row: any, idx: number) => {
                  const book = bookFromId(row.strategy_id ?? "");
                  return (
                    <tr key={`${row.intent_id}-${row.symbol}-${idx}`} className={`border-b border-vantage-border/50 ${row.side === "BUY" ? "bg-vantage-green/[0.03] hover:bg-vantage-green/[0.05]" : "bg-vantage-red/[0.03] hover:bg-vantage-red/[0.05]"}`}>
                      <td className="py-2 px-2 font-mono">{row.ny_date}</td>
                      <td className="py-2 px-2">
                        <span className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${book === "alpaca" ? "bg-vantage-amber/15 text-vantage-amber" : "bg-vantage-blue/15 text-vantage-blue"}`}>
                          {book === "alpaca" ? "ALP" : "SCH"}
                        </span>
                      </td>
                      <td className="py-2 px-2">
                        <Link to={`/strategies/${row.strategy_id}`} className="font-semibold text-vantage-text hover:text-vantage-blue transition-colors">
                          {getMeta(row.strategy_id).shortName}
                        </Link>
                      </td>
                      <td className="py-2 px-2 font-mono font-semibold">{row.symbol}</td>
                      <td className={`py-2 px-2 font-mono font-semibold ${row.side === "BUY" ? "text-vantage-green" : "text-vantage-red"}`}>{row.side}</td>
                      <td className="py-2 px-2 font-mono text-right">{row.delta_pct != null ? `${Number(row.delta_pct) > 0 ? "+" : ""}${Number(row.delta_pct).toFixed(1)}%` : "\u2014"}</td>
                      <td className="py-2 px-2 font-mono text-right">{row.target_pct != null ? `${Number(row.target_pct).toFixed(1)}%` : "\u2014"}</td>
                      <td className="py-2 px-2 font-mono text-right">{row.current_pct != null ? `${Number(row.current_pct).toFixed(1)}%` : "\u2014"}</td>
                      <td className="py-2 px-2 text-vantage-muted">{row.regime ?? "\u2014"}</td>
                      <td className="py-2 px-2 text-center">{row.posted ? <span className="text-vantage-green">\u2713</span> : <span className="text-vantage-muted">\u2014</span>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {sorted.length === 0 && <EmptyState icon={ScrollText} message="No trades match the current filters" />}
        </div>
      )}
    </div>
  );
}
