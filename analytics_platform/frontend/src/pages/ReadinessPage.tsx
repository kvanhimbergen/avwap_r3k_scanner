import { api } from "../api";
import { ErrorState } from "../components/ErrorState";
import { LoadingState } from "../components/LoadingState";
import { usePolling } from "../hooks/usePolling";
import type { ReadinessStrategy } from "../types";

export function ReadinessPage() {
  const readiness = usePolling(() => api.raecReadiness(), 60_000);

  if (readiness.loading) return <LoadingState text="Loading readiness..." />;
  if (readiness.error) return <ErrorState error={readiness.error} />;

  const strategies = (readiness.data?.data.strategies ?? []) as ReadinessStrategy[];
  const totalWarnings = strategies.reduce((n, s) => n + s.warnings.length, 0);

  return (
    <section>
      <h2 className="page-title">RAEC Readiness</h2>

      {totalWarnings === 0 ? (
        <div className="banner banner-ok">All strategies are healthy — no warnings.</div>
      ) : (
        <div className="banner banner-warn">
          {totalWarnings} warning(s) across {strategies.filter((s) => s.warnings.length > 0).length} strategy(ies).
        </div>
      )}

      <div className="readiness-grid">
        {strategies.map((strategy) => (
          <div
            key={strategy.strategy_id}
            className={`readiness-card ${strategy.warnings.length === 0 ? "readiness-ok" : "readiness-warn"}`}
          >
            <h4>{strategy.strategy_id}</h4>
            <div>
              State: {strategy.state_file_exists ? <span className="readiness-check">OK</span> : <span className="readiness-x">MISSING</span>}
            </div>
            <div>Last Eval: {strategy.last_eval_date ?? "Never"}</div>
            <div>
              Regime:{" "}
              <span className={`regime-badge ${strategy.last_regime?.toLowerCase().replace("_", "-") ?? ""}`}>
                {strategy.last_regime ?? "\u2014"}
              </span>
            </div>
            <div>
              Allocations: {strategy.allocation_count} ({strategy.total_weight_pct.toFixed(1)}%)
            </div>
            <div>Ledger Today: {strategy.ledger_files_today}</div>
            {strategy.warnings.length > 0 && (
              <ul className="warning-list">
                {strategy.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
