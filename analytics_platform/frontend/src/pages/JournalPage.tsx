import { useMemo, useState } from "react";

import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { KpiCard } from "../components/KpiCard";
import { LoadingState } from "../components/LoadingState";
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

type SortKey = "ny_date" | "strategy_id" | "symbol" | "side" | "delta_pct" | "target_pct" | "current_pct";

export function JournalPage() {
  const [strategyId, setStrategyId] = useState("");
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("ny_date");
  const [sortAsc, setSortAsc] = useState(false);

  const journal = usePolling(
    () =>
      api.journal({
        strategy_id: strategyId || undefined,
        symbol: symbol || undefined,
        side: side || undefined,
        limit: 500,
      }),
    45_000,
  );

  const rows = (journal.data?.data as Record<string, any>)?.rows as Array<Record<string, any>> ?? [];

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      const av = a[sortKey] ?? "";
      const bv = b[sortKey] ?? "";
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
    return copy;
  }, [rows, sortKey, sortAsc]);

  const kpis = useMemo(() => {
    const buys = rows.filter((r) => r.side === "BUY").length;
    const sells = rows.filter((r) => r.side === "SELL").length;
    const symbols = new Set(rows.map((r) => r.symbol)).size;
    return { total: rows.length, buys, sells, symbols };
  }, [rows]);

  if (journal.loading) return <LoadingState text="Loading journal..." />;
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

  return (
    <section>
      <h2 className="page-title">Trade Journal</h2>

      <div className="helper-card">
        <h3 className="helper-title">How To Read This</h3>
        <p className="helper-text">
          Every rebalance intent across all strategies appears here. Use filters to isolate a
          single strategy or symbol. <strong>Delta%</strong> shows the size of the position change,
          while <strong>Target%</strong> and <strong>Current%</strong> show where the position is heading
          versus where it was.
        </p>
      </div>

      <div className="filter-row">
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
      </div>

      <div className="kpi-grid">
        <KpiCard label="Total Trades" value={kpis.total} />
        <KpiCard label="Buys" value={kpis.buys} />
        <KpiCard label="Sells" value={kpis.sells} />
        <KpiCard label="Unique Symbols" value={kpis.symbols} />
      </div>

      <div className="table-card">
        <table>
          <thead>
            <tr>
              {sortHeader("Date", "ny_date")}
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
            {sorted.map((row, idx) => (
              <tr
                key={`${row.intent_id}-${row.symbol}-${idx}`}
                style={{ color: row.side === "BUY" ? "#0f9d58" : row.side === "SELL" ? "#d93025" : undefined }}
              >
                <td>{row.ny_date}</td>
                <td>{row.strategy_id}</td>
                <td>{row.symbol}</td>
                <td>{row.side}</td>
                <td>{row.delta_pct != null ? `${Number(row.delta_pct).toFixed(1)}%` : "—"}</td>
                <td>{row.target_pct != null ? `${Number(row.target_pct).toFixed(1)}%` : "—"}</td>
                <td>{row.current_pct != null ? `${Number(row.current_pct).toFixed(1)}%` : "—"}</td>
                <td>{row.regime ?? "—"}</td>
                <td>{row.posted == null ? "—" : row.posted ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
