import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { SkeletonLoader } from "./components/SkeletonLoader";

/* ── Eager: Command Center (home — always fast) ──── */
import { CommandCenter } from "./pages/CommandCenter";

/* ── Lazy-loaded pages ──── */
const StrategyRoster = lazy(() =>
  import("./pages/StrategyRoster").then((m) => ({ default: m.StrategyRoster })),
);
const StrategyTearsheet = lazy(() =>
  import("./pages/StrategyTearsheet").then((m) => ({ default: m.StrategyTearsheet })),
);
const RiskPage = lazy(() =>
  import("./pages/RiskPage").then((m) => ({ default: m.RiskPage })),
);
const BlotterPage = lazy(() =>
  import("./pages/BlotterPage").then((m) => ({ default: m.BlotterPage })),
);
const ExecutionPage = lazy(() =>
  import("./pages/ExecutionPage").then((m) => ({ default: m.ExecutionPage })),
);
const BacktestsPage = lazy(() =>
  import("./pages/BacktestsPage").then((m) => ({ default: m.BacktestsPage })),
);
const S2SignalsPage = lazy(() =>
  import("./pages/S2SignalsPage").then((m) => ({ default: m.S2SignalsPage })),
);
const LogFillsPage = lazy(() =>
  import("./pages/LogFillsPage").then((m) => ({ default: m.LogFillsPage })),
);
const SystemPage = lazy(() =>
  import("./pages/SystemPage").then((m) => ({ default: m.SystemPage })),
);

function PageFallback() {
  return (
    <section>
      <SkeletonLoader variant="card" />
      <SkeletonLoader variant="chart" />
    </section>
  );
}

export function App() {
  return (
    <AppShell>
      <Suspense fallback={<PageFallback />}>
        <Routes>
          {/* ── Command Center (home) ── */}
          <Route path="/" element={<CommandCenter />} />

          {/* ── Strategy Roster + Tearsheet ── */}
          <Route path="/strategies" element={<StrategyRoster />} />
          <Route path="/strategies/:id" element={<StrategyTearsheet />} />

          {/* ── Risk Monitor ── */}
          <Route path="/risk" element={<RiskPage />} />

          {/* ── Blotter ── */}
          <Route path="/blotter" element={<BlotterPage />} />

          {/* ── Execution (merged Slippage + Trade Analytics) ── */}
          <Route path="/execution" element={<ExecutionPage />} />

          {/* ── Research ── */}
          <Route path="/research" element={<Navigate to="/research/backtests" replace />} />
          <Route path="/research/backtests" element={<BacktestsPage />} />
          <Route path="/research/signals" element={<S2SignalsPage />} />

          {/* ── Ops ── */}
          <Route path="/ops" element={<Navigate to="/ops/log-fills" replace />} />
          <Route path="/ops/log-fills" element={<LogFillsPage />} />
          <Route path="/ops/system" element={<SystemPage />} />

          {/* ── Legacy route redirects ── */}
          <Route path="/journal" element={<Navigate to="/blotter" replace />} />
          <Route path="/decisions" element={<Navigate to="/risk" replace />} />
          <Route path="/pnl" element={<Navigate to="/risk" replace />} />
          <Route path="/portfolio" element={<Navigate to="/" replace />} />
          <Route path="/help" element={<Navigate to="/ops/system" replace />} />
          <Route path="/backtests" element={<Navigate to="/research/backtests" replace />} />
          <Route path="/signals/s2" element={<Navigate to="/research/signals" replace />} />
          <Route path="/analytics/trades" element={<Navigate to="/execution" replace />} />
          <Route path="/execution/slippage" element={<Navigate to="/execution" replace />} />
          <Route path="/execution/trades" element={<Navigate to="/execution" replace />} />
          <Route path="/legacy/overview" element={<Navigate to="/" replace />} />
          <Route path="/raec" element={<Navigate to="/strategies" replace />} />
          <Route path="/raec/readiness" element={<Navigate to="/strategies" replace />} />
          <Route path="/raec/log-fills" element={<Navigate to="/ops/log-fills" replace />} />
          <Route path="/strategies/matrix" element={<Navigate to="/strategies" replace />} />
          <Route path="/slippage" element={<Navigate to="/execution" replace />} />

          {/* ── Catch-all ── */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}
