import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { LastRefreshed } from "../components/LastRefreshed";
import { SkeletonLoader } from "../components/SkeletonLoader";
import { SummaryStrip } from "../components/SummaryStrip";
import { usePolling } from "../hooks/usePolling";

const ALL_STRATEGIES = [
  { id: "", label: "All Strategies" },
  { id: "S1_AVWAP_CORE", label: "S1 AVWAP Core" },
  { id: "S2_LETF_ORB_AGGRO", label: "S2 LETF ORB" },
  { id: "RAEC_401K_V1", label: "RAEC V1" },
  { id: "RAEC_401K_V2", label: "RAEC V2" },
  { id: "RAEC_401K_V3", label: "RAEC V3" },
  { id: "RAEC_401K_V4", label: "RAEC V4" },
  { id: "RAEC_401K_V5", label: "RAEC V5" },
  { id: "RAEC_401K_COORD", label: "Coordinator" },
];

const ALL_BOOKS = [
  { id: "", label: "All Books" },
  { id: "ALP", label: "Alpaca Paper" },
  { id: "SCH", label: "Schwab 401K" },
];

const DATE_PRESETS = [
  { id: "", label: "All Time" },
  { id: "1", label: "Today" },
  { id: "7", label: "Last 7d" },
  { id: "30", label: "Last 30d" },
  { id: "custom", label: "Custom" },
];

type SortKey = "ny_date" | "strategy_id" | "symbol" | "side" | "delta_pct" | "target_pct" | "current_pct";

function bookFromStrategy(strategyId: string): "ALP" | "SCH" {
  if (strategyId.startsWith("S1_") || strategyId.startsWith("S2_")) return "ALP";
  return "SCH";
}

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
    if (!datePreset || datePreset === "custom") return undefined;
    return daysAgoStr(Number(datePreset));
  }, [datePreset]);

  const journal = usePolling(
    () =>
      api.journal({
        strategy_id: strategyId || undefined,
        symbol: symbol || undefined,
        side: side || undefined,
        start: startDate,
        limit: 500,
      }),
    45_000,
  );

  const rows = (journal.data?.data as Record<string, any>)?.rows as Array<Record<string, any>> ?? [];

  // Apply book filter client-side
  const bookFiltered = useMemo(() => {
    if (!bookFilter) return rows;
    return rows.filter((r) => bookFromStrategy(r.strategy_id ?? "") === bookFilter);
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
    const buys = bookFiltered.filter((r) => r.side === "BUY").length;
    const sells = bookFiltered.filter((r) => r.side === "SELL").length;
    const symbols = new Set(bookFiltered.map((r) => r.symbol)).size;
    const ratio = sells > 0 ? (buys / sells).toFixed(1) : "—";
    return { total: bookFiltered.length, buys, sells, symbols, ratio };
  }, [bookFiltered]);

  if (journal.error) return <ErrorState error={journal.error} />;

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  }

  function sortHeader(label: string, key: SortKey) {
    const arrow = sortKey === key ? (sortAsc ? " \u25B2" : " \u25BC") : "";
    return (
      <th onClick={() => handleSort(key)} style={{ cursor: "pointer" }}>
        {label}{arrow}
      </th>
    );
  }

  function handleExportCsv() {
    if (sorted.length === 0) return;
    const headers = ["Date", "Book", "Strategy", "Symbol", "Side", "Delta%", "Target%", "Current%", "Regime", "Posted"];
    const csvRows = sorted.map((row) => [
      row.ny_date,
      bookFromStrategy(row.strategy_id ?? ""),
      row.strategy_id,
      row.symbol,
      row.side,
      row.delta_pct != null ? Number(row.delta_pct).toFixed(1) : "",
      row.target_pct != null ? Number(row.target_pct).toFixed(1) : "",
      row.current_pct != null ? Number(row.current_pct).toFixed(1) : "",
      row.regime ?? "",
      row.posted == null ? "" : row.posted ? "Yes" : "No",
    ]);
    const csv = [headers.join(","), ...csvRows.map((r) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `blotter-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <section>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h2 className="page-title">Blotter</h2>
          <LastRefreshed at={journal.lastRefreshed} />
        </div>
        <button className="btn btn-secondary" onClick={handleExportCsv} disabled={sorted.length === 0}>
          Export CSV
        </button>
      </div>
      <p className="page-subtitle">Unified trade journal across all strategies and books</p>

      {/* Filters */}
      <div className="filter-row">
        <select value={bookFilter} onChange={(e) => setBookFilter(e.target.value)}>
          {ALL_BOOKS.map((b) => (
            <option key={b.id} value={b.id}>{b.label}</option>
          ))}
        </select>
        <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
          {ALL_STRATEGIES.map((s) => (
            <option key={s.id} value={s.id}>{s.label}</option>
          ))}
        </select>
        <input
          placeholder="Filter symbol"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
        />
        <select value={side} onChange={(e) => setSide(e.target.value)}>
          <option value="">All Sides</option>
          <option value="BUY">BUY</option>
          <option value="SELL">SELL</option>
        </select>
        <select value={datePreset} onChange={(e) => setDatePreset(e.target.value)}>
          {DATE_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
      </div>

      {/* Summary Strip */}
      {journal.loading ? (
        <SkeletonLoader variant="card" />
      ) : (
        <SummaryStrip
          items={[
            { label: "Total", value: kpis.total },
            { label: "Buys", value: kpis.buys },
            { label: "Sells", value: kpis.sells },
            { label: "Symbols", value: kpis.symbols },
            { label: "B/S", value: kpis.ratio },
          ]}
        />
      )}

      {/* Table */}
      {journal.loading ? (
        <SkeletonLoader variant="chart" />
      ) : (
        <div className="table-card">
          <table>
            <thead>
              <tr>
                {sortHeader("Date", "ny_date")}
                <th>Book</th>
                {sortHeader("Strategy", "strategy_id")}
                {sortHeader("Symbol", "symbol")}
                {sortHeader("Side", "side")}
                {sortHeader("Delta%", "delta_pct")}
                {sortHeader("Target%", "target_pct")}
                {sortHeader("Current%", "current_pct")}
                <th>Regime</th>
                <th>Posted</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((row, idx) => {
                const book = bookFromStrategy(row.strategy_id ?? "");
                return (
                  <tr key={`${row.intent_id}-${row.symbol}-${idx}`}>
                    <td className="mono">{row.ny_date}</td>
                    <td>
                      <span className={`book-badge ${book === "ALP" ? "alpaca" : "schwab"}`}>
                        {book}
                      </span>
                    </td>
                    <td>
                      <Link
                        to={`/strategies/${row.strategy_id}`}
                        style={{ color: "var(--text)", textDecoration: "none", fontWeight: 600, fontSize: "0.78rem" }}
                      >
                        {row.strategy_id}
                      </Link>
                    </td>
                    <td className="mono">{row.symbol}</td>
                    <td className={row.side === "BUY" ? "side-buy" : row.side === "SELL" ? "side-sell" : ""}>
                      {row.side}
                    </td>
                    <td className="mono">{row.delta_pct != null ? `${Number(row.delta_pct).toFixed(1)}%` : "—"}</td>
                    <td className="mono">{row.target_pct != null ? `${Number(row.target_pct).toFixed(1)}%` : "—"}</td>
                    <td className="mono">{row.current_pct != null ? `${Number(row.current_pct).toFixed(1)}%` : "—"}</td>
                    <td>{row.regime ?? "—"}</td>
                    <td>{row.posted == null ? "—" : row.posted ? "Yes" : "No"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {sorted.length === 0 && (
            <div className="empty-state">
              <div className="empty-state-icon">=</div>
              No trades match the current filters
            </div>
          )}
        </div>
      )}
    </section>
  );
}
