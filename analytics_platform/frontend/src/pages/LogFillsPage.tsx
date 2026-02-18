import { useCallback, useEffect, useState } from "react";

import { api } from "../api";

const STRATEGY_OPTIONS = [
  { id: "RAEC_401K_COORD", label: "Coordinator" },
  { id: "RAEC_401K_V3", label: "RAEC V3" },
  { id: "RAEC_401K_V4", label: "RAEC V4" },
  { id: "RAEC_401K_V5", label: "RAEC V5" },
  { id: "RAEC_401K_V1", label: "RAEC V1" },
  { id: "RAEC_401K_V2", label: "RAEC V2" },
];

interface FillRow {
  side: string;
  symbol: string;
  qty: string;
  price: string;
}

const EMPTY_ROW: FillRow = { side: "BUY", symbol: "", qty: "", price: "" };

function todayStr(): string {
  const d = new Date();
  return d.toISOString().slice(0, 10);
}

export function LogFillsPage() {
  const [date, setDate] = useState(todayStr);
  const [strategyId, setStrategyId] = useState("RAEC_401K_COORD");
  const [rows, setRows] = useState<FillRow[]>([{ ...EMPTY_ROW }]);
  const [fees, setFees] = useState("0");
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState<{ type: "ok" | "error"; message: string } | null>(null);
  const [recentFills, setRecentFills] = useState<Record<string, unknown>[]>([]);

  const loadRecent = useCallback(async (d: string) => {
    try {
      const resp = await api.getFills(d);
      const data = resp.data as Record<string, unknown>;
      setRecentFills((data?.records as Record<string, unknown>[]) ?? []);
    } catch {
      // silently ignore — recent fills is auxiliary
    }
  }, []);

  useEffect(() => {
    if (date) void loadRecent(date);
  }, [date, loadRecent]);

  function updateRow(idx: number, field: keyof FillRow, value: string) {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, [field]: value } : r)));
  }

  function addRow() {
    setRows((prev) => [...prev, { ...EMPTY_ROW }]);
  }

  function removeRow(idx: number) {
    setRows((prev) => (prev.length <= 1 ? prev : prev.filter((_, i) => i !== idx)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setToast(null);
    setSubmitting(true);

    const fills = rows
      .filter((r) => r.symbol.trim() && r.price.trim())
      .map((r) => ({
        side: r.side,
        symbol: r.symbol.trim().toUpperCase(),
        qty: r.qty.trim() ? Number(r.qty) : null,
        price: Number(r.price),
      }));

    if (fills.length === 0) {
      setToast({ type: "error", message: "Add at least one fill with a symbol and price." });
      setSubmitting(false);
      return;
    }

    try {
      const resp = await api.postFills({
        date,
        strategy_id: strategyId,
        fees: Number(fees) || 0,
        notes: notes.trim() || null,
        fills,
      });
      const data = resp.data as Record<string, unknown>;
      const logged = data.logged as number;
      const skipped = data.skipped as number;
      setToast({
        type: "ok",
        message: `Logged ${logged} fill(s)${skipped ? `, skipped ${skipped} duplicate(s)` : ""}.`,
      });
      setRows([{ ...EMPTY_ROW }]);
      setFees("0");
      setNotes("");
      void loadRecent(date);
    } catch (err) {
      setToast({
        type: "error",
        message: err instanceof Error ? err.message : "Failed to log fills.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section>
      <h2 className="page-title">Log Fills</h2>
      <p className="page-subtitle">Record manual Schwab 401(k) fills</p>

      <div className="helper-card">
        <h3 className="helper-title">Fill Format</h3>
        <p className="helper-text">
          Enter each fill as a row below. <strong>Symbol</strong> and <strong>Price</strong> are
          required. <strong>Qty</strong> is optional (e.g. for price-only tracking). Duplicates
          (same date + strategy + symbol + side + qty + price) are automatically skipped.
        </p>
      </div>

      {toast && (
        <div className={`banner ${toast.type === "ok" ? "banner-ok" : "banner-error"}`}>
          {toast.message}
        </div>
      )}

      <div className="table-card">
        <h3>New Fills</h3>
        <form className="fill-form" onSubmit={handleSubmit}>
          <div className="fill-form-header">
            <label>
              Date
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} required />
            </label>
            <label>
              Strategy
              <select value={strategyId} onChange={(e) => setStrategyId(e.target.value)}>
                {STRATEGY_OPTIONS.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Fees
              <input
                type="number"
                step="0.01"
                min="0"
                value={fees}
                onChange={(e) => setFees(e.target.value)}
                className="fill-input-sm"
              />
            </label>
          </div>

          <div className="fill-rows">
            {rows.map((row, idx) => (
              <div className="fill-row" key={idx}>
                <select value={row.side} onChange={(e) => updateRow(idx, "side", e.target.value)}>
                  <option value="BUY">BUY</option>
                  <option value="SELL">SELL</option>
                </select>
                <input
                  placeholder="Symbol"
                  value={row.symbol}
                  onChange={(e) => updateRow(idx, "symbol", e.target.value.toUpperCase())}
                  required
                  className="fill-input-symbol"
                />
                <input
                  type="number"
                  placeholder="Qty"
                  min="0"
                  step="any"
                  value={row.qty}
                  onChange={(e) => updateRow(idx, "qty", e.target.value)}
                  className="fill-input-sm"
                />
                <input
                  type="number"
                  placeholder="Price"
                  min="0"
                  step="0.01"
                  value={row.price}
                  onChange={(e) => updateRow(idx, "price", e.target.value)}
                  required
                  className="fill-input-sm"
                />
                <button
                  type="button"
                  className="btn btn-icon"
                  onClick={() => removeRow(idx)}
                  title="Remove row"
                  disabled={rows.length <= 1}
                >
                  x
                </button>
              </div>
            ))}
          </div>

          <button type="button" className="btn btn-secondary" onClick={addRow}>
            + Add Row
          </button>

          <label className="fill-notes-label">
            Notes
            <input
              type="text"
              placeholder="Optional notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              className="fill-input-notes"
            />
          </label>

          <div className="fill-form-actions">
            <button type="submit" className="btn btn-primary" disabled={submitting}>
              {submitting ? "Submitting..." : "Log Fills"}
            </button>
          </div>
        </form>
      </div>

      {recentFills.length > 0 && (
        <div className="table-card" style={{ marginTop: 16 }}>
          <h3>Today's Fills ({recentFills.length})</h3>
          <table>
            <thead>
              <tr>
                <th>Side</th>
                <th>Symbol</th>
                <th>Qty</th>
                <th>Price</th>
                <th>Strategy</th>
                <th>Fees</th>
                <th>Fill ID</th>
              </tr>
            </thead>
            <tbody>
              {recentFills.map((r, i) => (
                <tr key={i}>
                  <td className={r.side === "BUY" ? "side-buy" : "side-sell"}>
                    {String(r.side)}
                  </td>
                  <td className="mono">{String(r.symbol)}</td>
                  <td className="mono">{r.qty != null ? String(r.qty) : "—"}</td>
                  <td className="mono">{String(r.price)}</td>
                  <td>{String(r.strategy_id)}</td>
                  <td className="mono">{String(r.fees ?? 0)}</td>
                  <td className="mono" title={String(r.fill_id)}>
                    {String(r.fill_id ?? "").slice(0, 12)}...
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
