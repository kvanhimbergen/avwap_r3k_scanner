/**
 * Trade Log — /trade-log
 * Manual trade execution tracker with R-multiple P&L.
 */
import { useCallback, useMemo, useState } from "react";
import { ClipboardList } from "lucide-react";
import { useSearchParams } from "react-router-dom";

import { api } from "../api";
import { SkeletonCard, SkeletonTable } from "../components/Skeleton";
import { EmptyState } from "../components/EmptyState";
import { ErrorState } from "../components/ErrorState";
import { usePolling } from "../hooks/usePolling";
import type { TradeLogEntry, TradeLogSummary } from "../types";

function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v == null) return "\u2014";
  return Number(v).toFixed(digits);
}

function TradeEntryForm({ onCreated, prefill }: { onCreated: () => void; prefill?: Record<string, string> }) {
  const today = new Date().toISOString().slice(0, 10);
  const [form, setForm] = useState({
    entry_date: prefill?.entry_date ?? today,
    symbol: prefill?.symbol ?? "",
    direction: prefill?.direction ?? "long",
    entry_price: prefill?.entry_price ?? "",
    qty: prefill?.qty ?? "",
    stop_loss: prefill?.stop_loss ?? "",
    target_r1: prefill?.target_r1 ?? "",
    target_r2: prefill?.target_r2 ?? "",
    strategy_source: prefill?.strategy_source ?? "AVWAP_SCAN",
    notes: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.tradeLogCreate({
        entry_date: form.entry_date,
        symbol: form.symbol.toUpperCase(),
        direction: form.direction,
        entry_price: parseFloat(form.entry_price),
        qty: parseInt(form.qty, 10),
        stop_loss: parseFloat(form.stop_loss),
        target_r1: form.target_r1 ? parseFloat(form.target_r1) : undefined,
        target_r2: form.target_r2 ? parseFloat(form.target_r2) : undefined,
        strategy_source: form.strategy_source || undefined,
        notes: form.notes || undefined,
      });
      setForm({ ...form, symbol: "", entry_price: "", qty: "", stop_loss: "", target_r1: "", target_r2: "", notes: "" });
      onCreated();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  }

  const inputCls = "bg-vantage-bg border border-vantage-border rounded px-2 py-1.5 text-xs font-mono text-vantage-text focus:outline-none focus:border-vantage-blue/50";

  return (
    <form onSubmit={handleSubmit} className="bg-vantage-card border border-vantage-border rounded-lg p-4 space-y-3">
      <p className="text-[11px] text-vantage-muted uppercase tracking-wide font-semibold">New Trade</p>
      {error && <p className="text-xs text-vantage-red">{error}</p>}
      <div className="grid grid-cols-4 gap-3">
        <input placeholder="Symbol" value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value })} className={inputCls} required />
        <select value={form.direction} onChange={(e) => setForm({ ...form, direction: e.target.value })} className={inputCls}>
          <option value="long">Long</option>
          <option value="short">Short</option>
        </select>
        <input type="date" value={form.entry_date} onChange={(e) => setForm({ ...form, entry_date: e.target.value })} className={inputCls} required />
        <input placeholder="Qty" value={form.qty} onChange={(e) => setForm({ ...form, qty: e.target.value })} className={inputCls} required type="number" min="1" />
      </div>
      <div className="grid grid-cols-4 gap-3">
        <input placeholder="Entry $" value={form.entry_price} onChange={(e) => setForm({ ...form, entry_price: e.target.value })} className={inputCls} required type="number" step="0.01" />
        <input placeholder="Stop $" value={form.stop_loss} onChange={(e) => setForm({ ...form, stop_loss: e.target.value })} className={inputCls} required type="number" step="0.01" />
        <input placeholder="R1 $" value={form.target_r1} onChange={(e) => setForm({ ...form, target_r1: e.target.value })} className={inputCls} type="number" step="0.01" />
        <input placeholder="R2 $" value={form.target_r2} onChange={(e) => setForm({ ...form, target_r2: e.target.value })} className={inputCls} type="number" step="0.01" />
      </div>
      <div className="flex items-center gap-3">
        <input placeholder="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={`${inputCls} flex-1`} />
        <button type="submit" disabled={submitting} className="px-4 py-1.5 bg-vantage-blue text-white text-xs font-medium rounded hover:bg-vantage-blue/80 disabled:opacity-50 transition-colors">
          {submitting ? "Saving..." : "Log Trade"}
        </button>
      </div>
    </form>
  );
}

export function TradeLogPage() {
  const [searchParams] = useSearchParams();
  const prefill = useMemo(() => {
    const p: Record<string, string> = {};
    searchParams.forEach((v, k) => { p[k] = v; });
    return Object.keys(p).length > 0 ? p : undefined;
  }, [searchParams]);

  const trades = usePolling(() => api.tradeLogList({ limit: 500 }), 60_000);
  const summary = usePolling(() => api.tradeLogSummary(), 60_000);

  const reload = useCallback(() => {
    void trades.refresh();
    void summary.refresh();
  }, [trades.refresh, summary.refresh]);

  const data = trades.data?.data as any;
  const rows = (data?.trades ?? []) as TradeLogEntry[];
  const summaryData = summary.data?.data as TradeLogSummary | undefined;

  const [closingId, setClosingId] = useState<string | null>(null);
  const [closePrice, setClosePrice] = useState("");

  async function handleClose(id: string) {
    if (!closePrice) return;
    try {
      await api.tradeLogClose(id, { exit_price: parseFloat(closePrice), exit_reason: "manual" });
      setClosingId(null);
      setClosePrice("");
      reload();
    } catch {}
  }

  async function handleDelete(id: string) {
    try {
      await api.tradeLogDelete(id);
      reload();
    } catch {}
  }

  if (trades.error) return <ErrorState message={trades.error} />;

  return (
    <div className="p-6 space-y-4 max-w-[1600px] mx-auto">
      <div className="flex items-center gap-3">
        <ClipboardList size={24} className="text-vantage-blue" />
        <div>
          <h2 className="text-xl font-semibold">Trade Log</h2>
          <p className="text-[11px] text-vantage-muted">Manual trade execution tracker</p>
        </div>
      </div>

      {/* KPIs */}
      {summary.loading ? (
        <div className="grid grid-cols-5 gap-4">{[...Array(5)].map((_, i) => <SkeletonCard key={i} />)}</div>
      ) : summaryData ? (
        <div className="grid grid-cols-5 gap-4">
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Open</p>
            <p className="font-mono text-2xl font-bold">{summaryData.open_count}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Closed</p>
            <p className="font-mono text-2xl font-bold">{summaryData.closed_count}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Win Rate</p>
            <p className="font-mono text-2xl font-bold">{summaryData.win_rate != null ? `${summaryData.win_rate}%` : "\u2014"}</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Avg R</p>
            <p className={`font-mono text-2xl font-bold ${(summaryData.avg_r_multiple ?? 0) >= 0 ? "text-vantage-green" : "text-vantage-red"}`}>{fmtNum(summaryData.avg_r_multiple, 2)}R</p>
          </div>
          <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
            <p className="text-[11px] text-vantage-muted uppercase tracking-wide mb-1">Total P&L</p>
            <p className={`font-mono text-2xl font-bold ${summaryData.total_pnl >= 0 ? "text-vantage-green" : "text-vantage-red"}`}>${fmtNum(summaryData.total_pnl)}</p>
          </div>
        </div>
      ) : null}

      {/* Entry Form */}
      <TradeEntryForm onCreated={reload} prefill={prefill} />

      {/* Trade Table */}
      {trades.loading ? (
        <SkeletonTable />
      ) : (
        <div className="bg-vantage-card border border-vantage-border rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="border-b border-vantage-border">
                <th className="py-2 px-2 text-left text-vantage-muted font-medium">Date</th>
                <th className="py-2 px-2 text-left text-vantage-muted font-medium">Symbol</th>
                <th className="py-2 px-2 text-left text-vantage-muted font-medium">Dir</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Qty</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Entry</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Stop</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">Exit</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">R</th>
                <th className="py-2 px-2 text-right text-vantage-muted font-medium">P&L</th>
                <th className="py-2 px-2 text-left text-vantage-muted font-medium">Status</th>
                <th className="py-2 px-2 text-vantage-muted font-medium">Actions</th>
              </tr></thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id} className="border-b border-vantage-border/50">
                    <td className="py-2 px-2 font-mono">{row.entry_date}</td>
                    <td className="py-2 px-2 font-mono font-semibold">{row.symbol}</td>
                    <td className={`py-2 px-2 font-mono ${row.direction === "long" ? "text-vantage-green" : "text-vantage-red"}`}>{row.direction}</td>
                    <td className="py-2 px-2 font-mono text-right">{row.qty}</td>
                    <td className="py-2 px-2 font-mono text-right">${fmtNum(row.entry_price)}</td>
                    <td className="py-2 px-2 font-mono text-right text-vantage-red">${fmtNum(row.stop_loss)}</td>
                    <td className="py-2 px-2 font-mono text-right">{row.exit_price != null ? `$${fmtNum(row.exit_price)}` : "\u2014"}</td>
                    <td className={`py-2 px-2 font-mono text-right font-semibold ${row.r_multiple != null ? (row.r_multiple >= 0 ? "text-vantage-green" : "text-vantage-red") : ""}`}>{row.r_multiple != null ? `${fmtNum(row.r_multiple)}R` : "\u2014"}</td>
                    <td className={`py-2 px-2 font-mono text-right ${row.pnl_dollars != null ? (row.pnl_dollars >= 0 ? "text-vantage-green" : "text-vantage-red") : ""}`}>{row.pnl_dollars != null ? `$${fmtNum(row.pnl_dollars)}` : "\u2014"}</td>
                    <td className="py-2 px-2"><span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${row.status === "open" ? "bg-vantage-blue/20 text-vantage-blue" : "bg-vantage-muted/20 text-vantage-muted"}`}>{row.status}</span></td>
                    <td className="py-2 px-2">
                      {row.status === "open" ? (
                        closingId === row.id ? (
                          <span className="flex items-center gap-1">
                            <input placeholder="Exit $" value={closePrice} onChange={(e) => setClosePrice(e.target.value)} className="w-16 bg-vantage-bg border border-vantage-border rounded px-1 py-0.5 text-[10px] font-mono" type="number" step="0.01" />
                            <button onClick={() => handleClose(row.id)} className="text-[10px] text-vantage-green hover:underline">OK</button>
                            <button onClick={() => { setClosingId(null); setClosePrice(""); }} className="text-[10px] text-vantage-muted hover:underline">X</button>
                          </span>
                        ) : (
                          <button onClick={() => setClosingId(row.id)} className="text-[10px] text-vantage-blue hover:underline">Close</button>
                        )
                      ) : null}
                      {" "}
                      <button onClick={() => handleDelete(row.id)} className="text-[10px] text-vantage-red hover:underline">Del</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {rows.length === 0 && <EmptyState icon={ClipboardList} message="No trades logged yet" />}
        </div>
      )}
    </div>
  );
}
