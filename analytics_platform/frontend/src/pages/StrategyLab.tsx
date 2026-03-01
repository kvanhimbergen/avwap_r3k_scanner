/**
 * Strategy Lab — /lab
 * AI-powered strategy experimentation page.
 * Pipeline funnel, experiment cards, detail slide-out with AI chat.
 */
import { useEffect, useState } from "react";
import { FlaskConical, Send, MessageCircle, X, Play, Pause, Trash2, ChevronDown } from "lucide-react";

import { StatusBadge, CountBadge } from "../components/Badge";
import { EmptyState } from "../components/EmptyState";

/* ── Types ──────────────────────────────────────── */

type ExperimentStatus = "idea" | "designing" | "backtesting" | "evaluating" | "promoted" | "rejected";

interface Experiment {
  id: string;
  name: string;
  thesis: string;
  status: ExperimentStatus;
  createdAt: string;
  sharpe?: number;
  maxDrawdown?: number;
  winRate?: number;
  notes?: string;
}

/* ── Pipeline stages ─────────────────────────────── */

const PIPELINE_STAGES: { key: ExperimentStatus; label: string; color: string }[] = [
  { key: "idea",        label: "Ideas",       color: "#9ca3af" },
  { key: "designing",   label: "Designing",   color: "#3b82f6" },
  { key: "backtesting", label: "Backtesting", color: "#f59e0b" },
  { key: "evaluating",  label: "Evaluating",  color: "#06b6d4" },
  { key: "promoted",    label: "Promoted",    color: "#10b981" },
];

const STATUS_BADGE_MAP: Record<ExperimentStatus, "disabled" | "info" | "warning" | "evaluating" | "active" | "error"> = {
  idea: "disabled",
  designing: "info",
  backtesting: "warning",
  evaluating: "evaluating",
  promoted: "active",
  rejected: "error",
};

/* ── Seed data (placeholder) ─────────────────────── */

const SEED_EXPERIMENTS: Experiment[] = [
  {
    id: "exp-001",
    name: "Dual Momentum + Regime Filter",
    thesis: "Combine relative + absolute momentum with E1 regime overlay to reduce whipsaw in V3-style allocations",
    status: "evaluating",
    createdAt: "2026-02-20",
    sharpe: 1.42,
    maxDrawdown: -8.3,
    winRate: 0.67,
  },
  {
    id: "exp-002",
    name: "Volatility-Weighted RAEC",
    thesis: "Weight sub-strategy allocations by inverse realized vol instead of fixed 40/30/30 split",
    status: "backtesting",
    createdAt: "2026-02-18",
    sharpe: 1.15,
    maxDrawdown: -11.2,
  },
  {
    id: "exp-003",
    name: "Sector Momentum Overlay",
    thesis: "Add GICS sector momentum tilt to broad market ETF allocation for V4 Macro variant",
    status: "designing",
    createdAt: "2026-02-22",
  },
  {
    id: "exp-004",
    name: "Trend-Follow + Mean-Revert Blend",
    thesis: "Blend trend-following signals with mean-reversion signals based on VIX regime",
    status: "idea",
    createdAt: "2026-02-24",
  },
  {
    id: "exp-005",
    name: "Risk Parity Sub-Strategy",
    thesis: "Equal risk contribution across asset classes rather than equal weight for more stable returns",
    status: "promoted",
    createdAt: "2026-02-10",
    sharpe: 1.58,
    maxDrawdown: -6.1,
    winRate: 0.72,
  },
  {
    id: "exp-006",
    name: "Options Collar Overlay",
    thesis: "Add protective collar (buy put, sell call) on concentrated positions to cap downside",
    status: "rejected",
    createdAt: "2026-02-14",
    sharpe: 0.43,
    maxDrawdown: -15.8,
    notes: "Collar cost too high relative to protection benefit in low-vol regimes",
  },
];

/* ── Detail Panel ────────────────────────────────── */

function DetailPanel({ experiment, onClose }: { experiment: Experiment; onClose: () => void }) {
  const [chatInput, setChatInput] = useState("");
  const [chatHistory, setChatHistory] = useState<{ role: "user" | "ai"; text: string }[]>([]);

  function handleSend() {
    if (!chatInput.trim()) return;
    setChatHistory((prev) => [
      ...prev,
      { role: "user", text: chatInput },
      { role: "ai", text: "I'd recommend backtesting this with a 252-day lookback window and comparing Sharpe against the base V3 config. Want me to generate the backtest parameters?" },
    ]);
    setChatInput("");
  }

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />

      {/* Panel */}
      <div role="dialog" aria-modal="true" aria-labelledby="lab-panel-title" className="fixed inset-y-0 right-0 w-[480px] bg-vantage-card border-l border-vantage-border z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className="shrink-0 p-4 border-b border-vantage-border flex items-center justify-between">
          <div>
            <h2 id="lab-panel-title" className="text-base font-semibold">{experiment.name}</h2>
            <StatusBadge variant={STATUS_BADGE_MAP[experiment.status]}>
              {experiment.status.toUpperCase()}
            </StatusBadge>
          </div>
          <button className="p-1 hover:bg-vantage-border rounded transition-colors" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {/* Thesis */}
          <div>
            <p className="text-[10px] text-vantage-muted uppercase tracking-wide mb-1">Thesis</p>
            <p className="text-xs text-vantage-text">{experiment.thesis}</p>
          </div>

          {/* Metrics */}
          {(experiment.sharpe != null || experiment.maxDrawdown != null || experiment.winRate != null) && (
            <div className="grid grid-cols-3 gap-3">
              {experiment.sharpe != null && (
                <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Sharpe</p>
                  <p className="font-mono text-lg font-bold text-vantage-text">{experiment.sharpe.toFixed(2)}</p>
                </div>
              )}
              {experiment.maxDrawdown != null && (
                <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Max DD</p>
                  <p className="font-mono text-lg font-bold text-vantage-red">{experiment.maxDrawdown.toFixed(1)}%</p>
                </div>
              )}
              {experiment.winRate != null && (
                <div className="bg-vantage-bg border border-vantage-border rounded-lg p-3">
                  <p className="text-[10px] text-vantage-muted uppercase tracking-wide">Win Rate</p>
                  <p className="font-mono text-lg font-bold text-vantage-green">{(experiment.winRate * 100).toFixed(0)}%</p>
                </div>
              )}
            </div>
          )}

          {/* Notes */}
          {experiment.notes && (
            <div>
              <p className="text-[10px] text-vantage-muted uppercase tracking-wide mb-1">Notes</p>
              <p className="text-xs text-vantage-muted bg-vantage-bg rounded p-2 border border-vantage-border/50">{experiment.notes}</p>
            </div>
          )}

          {/* Equity curve placeholder */}
          <div className="bg-vantage-bg border border-vantage-border rounded-lg p-4">
            <p className="text-[10px] text-vantage-muted uppercase tracking-wide mb-2">Equity Curve</p>
            <div className="h-[200px] flex items-center justify-center text-vantage-muted text-xs">
              {experiment.sharpe != null ? "Backtest chart will render here" : "Run backtest to generate equity curve"}
            </div>
          </div>
        </div>

        {/* AI Chat */}
        <div className="shrink-0 border-t border-vantage-border p-3">
          <div className="flex items-center gap-1.5 mb-2">
            <MessageCircle size={12} className="text-purple-400" />
            <span className="text-[10px] text-purple-400 font-medium">Ask AI About This Strategy</span>
          </div>

          {chatHistory.length > 0 && (
            <div className="space-y-2 mb-2 max-h-32 overflow-y-auto">
              {chatHistory.map((msg, i) => (
                <div key={i}>
                  {msg.role === "user" ? (
                    <div>
                      <span className="text-[9px] text-purple-400 uppercase tracking-wide">You</span>
                      <p className="text-xs text-vantage-text font-medium">{msg.text}</p>
                    </div>
                  ) : (
                    <div className="text-xs text-vantage-muted bg-vantage-bg rounded p-2 border border-vantage-border/50">
                      {msg.text}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="flex gap-2">
            <input
              className="flex-1 bg-vantage-bg border border-vantage-border rounded px-3 py-1.5 text-xs focus:border-purple-500/50 focus:outline-none text-vantage-text"
              placeholder="e.g., What lookback period should I use?"
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSend()}
            />
            <button
              className="p-1.5 rounded bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 disabled:opacity-40 transition-colors"
              onClick={handleSend}
              disabled={!chatInput.trim()}
            >
              <Send size={12} />
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

/* ── Main Component ──────────────────────────────── */

export function StrategyLab() {
  const [experiments] = useState<Experiment[]>(SEED_EXPERIMENTS);
  const [filterStatus, setFilterStatus] = useState<ExperimentStatus | "all">("all");
  const [selectedExperiment, setSelectedExperiment] = useState<Experiment | null>(null);

  const filtered = filterStatus === "all"
    ? experiments.filter((e) => e.status !== "rejected")
    : experiments.filter((e) => e.status === filterStatus);

  const stageCounts = PIPELINE_STAGES.map((s) => ({
    ...s,
    count: experiments.filter((e) => e.status === s.key).length,
  }));

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <FlaskConical size={24} className="text-purple-400" />
          <div>
            <h2 className="text-xl font-semibold">Strategy Lab <span className="text-[10px] font-bold text-vantage-amber bg-vantage-amber/15 px-1.5 py-0.5 rounded ml-2">PROTOTYPE</span></h2>
            <p className="text-[11px] text-vantage-muted">AI-powered strategy experimentation and research</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className="text-xs px-3 py-1.5 rounded bg-purple-500/20 text-purple-400 hover:bg-purple-500/30 transition-colors">
            Suggest Idea
          </button>
          <button className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-vantage-card border border-vantage-border rounded-lg hover:border-vantage-blue/50 transition-colors text-vantage-text">
            <Play size={12} /> Trigger New Ideas
          </button>
        </div>
      </div>

      {/* Pipeline Funnel */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3">Pipeline</h3>
        <div className="flex items-center gap-1">
          {stageCounts.map((stage, i) => (
            <div key={stage.key} className="flex items-center flex-1">
              <button
                onClick={() => setFilterStatus(stage.key)}
                className="flex-1 py-2 px-3 rounded text-center transition-colors hover:opacity-80"
                style={{ backgroundColor: `${stage.color}15` }}
              >
                <p className="font-mono text-lg font-bold" style={{ color: stage.color }}>{stage.count}</p>
                <p className="text-[10px] text-vantage-muted uppercase tracking-wide">{stage.label}</p>
              </button>
              {i < stageCounts.length - 1 && (
                <ChevronDown size={14} className="text-vantage-muted rotate-[-90deg] mx-1 shrink-0" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Filter tabs */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setFilterStatus("all")}
          className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors ${
            filterStatus === "all" ? "bg-vantage-border text-vantage-text" : "text-vantage-muted hover:text-vantage-text"
          }`}
        >
          All
        </button>
        {PIPELINE_STAGES.map((s) => (
          <button
            key={s.key}
            onClick={() => setFilterStatus(s.key)}
            className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors flex items-center gap-1 ${
              filterStatus === s.key ? "bg-vantage-border text-vantage-text" : "text-vantage-muted hover:text-vantage-text"
            }`}
          >
            {s.label}
            <CountBadge count={experiments.filter((e) => e.status === s.key).length} />
          </button>
        ))}
        <button
          onClick={() => setFilterStatus("rejected")}
          className={`px-2 py-0.5 rounded text-[11px] font-medium transition-colors flex items-center gap-1 ${
            filterStatus === "rejected" ? "bg-vantage-border text-vantage-text" : "text-vantage-muted hover:text-vantage-text"
          }`}
        >
          Rejected
          <CountBadge count={experiments.filter((e) => e.status === "rejected").length} />
        </button>
      </div>

      {/* Experiment Cards */}
      {filtered.length === 0 ? (
        <EmptyState icon={FlaskConical} message="No experiments match this filter" />
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((exp) => {
            const stageInfo = PIPELINE_STAGES.find((s) => s.key === exp.status);
            const color = stageInfo?.color ?? "#9ca3af";

            return (
              <div
                key={exp.id}
                onClick={() => setSelectedExperiment(exp)}
                className="bg-vantage-card border border-vantage-border rounded-lg p-4 border-l-2 cursor-pointer hover:border-vantage-blue/50 transition-colors"
                style={{ borderLeftColor: color }}
              >
                <div className="flex items-center justify-between mb-2">
                  <h4 className="text-sm font-semibold truncate pr-2">{exp.name}</h4>
                  <StatusBadge variant={STATUS_BADGE_MAP[exp.status]}>
                    {exp.status.toUpperCase()}
                  </StatusBadge>
                </div>

                <p className="text-xs text-vantage-muted line-clamp-2 mb-3">{exp.thesis}</p>

                {/* Metrics row */}
                {(exp.sharpe != null || exp.maxDrawdown != null || exp.winRate != null) && (
                  <div className="flex items-center gap-4 mb-3">
                    {exp.sharpe != null && (
                      <div>
                        <span className="text-[9px] text-vantage-muted uppercase">Sharpe</span>
                        <p className="font-mono text-xs font-semibold">{exp.sharpe.toFixed(2)}</p>
                      </div>
                    )}
                    {exp.maxDrawdown != null && (
                      <div>
                        <span className="text-[9px] text-vantage-muted uppercase">Max DD</span>
                        <p className="font-mono text-xs font-semibold text-vantage-red">{exp.maxDrawdown.toFixed(1)}%</p>
                      </div>
                    )}
                    {exp.winRate != null && (
                      <div>
                        <span className="text-[9px] text-vantage-muted uppercase">Win Rate</span>
                        <p className="font-mono text-xs font-semibold text-vantage-green">{(exp.winRate * 100).toFixed(0)}%</p>
                      </div>
                    )}
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <span className="text-[10px] text-vantage-muted">{exp.createdAt}</span>
                  <div className="flex items-center gap-1">
                    {exp.status === "idea" && (
                      <button className="p-1 rounded hover:bg-vantage-border transition-colors text-vantage-blue" title="Start designing">
                        <Play size={10} />
                      </button>
                    )}
                    {exp.status === "backtesting" && (
                      <button className="p-1 rounded hover:bg-vantage-border transition-colors text-vantage-amber" title="Pause">
                        <Pause size={10} />
                      </button>
                    )}
                    <button className="p-1 rounded hover:bg-vantage-border transition-colors text-vantage-muted" title="Delete">
                      <Trash2 size={10} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Activity Feed */}
      <div className="bg-vantage-card border border-vantage-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3">Lab Activity</h3>
        <div className="space-y-2 text-xs">
          <div className="flex items-center gap-2 py-1">
            <span className="font-mono text-vantage-muted w-20 shrink-0">Feb 24</span>
            <span className="text-purple-400 font-semibold w-8">AI</span>
            <span className="text-vantage-text">Generated 3 new strategy ideas from regime analysis</span>
          </div>
          <div className="flex items-center gap-2 py-1">
            <span className="font-mono text-vantage-muted w-20 shrink-0">Feb 22</span>
            <span className="text-vantage-blue font-semibold w-8">BT</span>
            <span className="text-vantage-text">Backtest completed: &quot;Volatility-Weighted RAEC&quot; — Sharpe 1.15</span>
          </div>
          <div className="flex items-center gap-2 py-1">
            <span className="font-mono text-vantage-muted w-20 shrink-0">Feb 20</span>
            <span className="text-vantage-green font-semibold w-8">OK</span>
            <span className="text-vantage-text">&quot;Risk Parity Sub-Strategy&quot; promoted to production</span>
          </div>
          <div className="flex items-center gap-2 py-1">
            <span className="font-mono text-vantage-muted w-20 shrink-0">Feb 14</span>
            <span className="text-vantage-red font-semibold w-8">NO</span>
            <span className="text-vantage-text">&quot;Options Collar Overlay&quot; rejected — poor risk-adjusted returns</span>
          </div>
        </div>
      </div>

      {/* Detail Panel */}
      {selectedExperiment && (
        <DetailPanel experiment={selectedExperiment} onClose={() => setSelectedExperiment(null)} />
      )}
    </div>
  );
}
