import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { Layout } from "./components/Layout";
import { Skeleton } from "./components/Skeleton";

/* ── Eager: Command Center (home — always fast) ──── */
import { CommandCenter } from "./pages/CommandCenter";

/* ── Lazy-loaded pages ──── */
const StrategyRoster = lazy(() =>
  import("./pages/StrategyRoster").then((m) => ({ default: m.StrategyRoster })),
);
const StrategyTearsheet = lazy(() =>
  import("./pages/StrategyTearsheet").then((m) => ({ default: m.StrategyTearsheet })),
);
const StrategyLab = lazy(() =>
  import("./pages/StrategyLab").then((m) => ({ default: m.StrategyLab })),
);
const RiskPage = lazy(() =>
  import("./pages/RiskPage").then((m) => ({ default: m.RiskPage })),
);
const TradePage = lazy(() =>
  import("./pages/TradePage").then((m) => ({ default: m.TradePage })),
);
const BlotterPage = lazy(() =>
  import("./pages/BlotterPage").then((m) => ({ default: m.BlotterPage })),
);
const PerformancePage = lazy(() =>
  import("./pages/PerformancePage").then((m) => ({ default: m.PerformancePage })),
);
const ScanPage = lazy(() =>
  import("./pages/ScanPage").then((m) => ({ default: m.ScanPage })),
);
const SchwabAccountPage = lazy(() =>
  import("./pages/SchwabAccountPage").then((m) => ({ default: m.SchwabAccountPage })),
);
const TradeLogPage = lazy(() =>
  import("./pages/TradeLogPage").then((m) => ({ default: m.TradeLogPage })),
);
const RebalancePage = lazy(() =>
  import("./pages/RebalancePage").then((m) => ({ default: m.RebalancePage })),
);
const SystemPage = lazy(() =>
  import("./pages/SystemPage").then((m) => ({ default: m.SystemPage })),
);

function PageFallback() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
        <Skeleton className="h-24" />
      </div>
      <Skeleton className="h-[300px]" />
    </div>
  );
}

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route
          path="/"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <CommandCenter />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/strategies"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <StrategyRoster />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/strategies/:id"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <StrategyTearsheet />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/trade"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <TradePage />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/lab"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <StrategyLab />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/blotter"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <BlotterPage />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/performance"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <PerformancePage />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/risk"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <RiskPage />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/scan"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <ScanPage />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/trade-log"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <TradeLogPage />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/ops"
          element={<Navigate to="/ops/schwab" replace />}
        />
        <Route
          path="/ops/schwab"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <SchwabAccountPage />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/ops/rebalance"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <RebalancePage />
            </Suspense></ErrorBoundary>
          }
        />
        <Route
          path="/ops/system"
          element={
            <ErrorBoundary><Suspense fallback={<PageFallback />}>
              <SystemPage />
            </Suspense></ErrorBoundary>
          }
        />

        {/* Legacy redirects */}
        <Route path="/journal" element={<Navigate to="/blotter" replace />} />
        <Route path="/decisions" element={<Navigate to="/risk" replace />} />
        <Route path="/pnl" element={<Navigate to="/risk" replace />} />
        <Route path="/portfolio" element={<Navigate to="/" replace />} />
        <Route path="/raec" element={<Navigate to="/strategies" replace />} />
        <Route path="/raec/readiness" element={<Navigate to="/strategies" replace />} />
        <Route path="/raec/log-fills" element={<Navigate to="/ops/schwab" replace />} />
        <Route path="/ops/log-fills" element={<Navigate to="/ops/schwab" replace />} />
        <Route path="/research" element={<Navigate to="/performance" replace />} />
        <Route path="/research/backtests" element={<Navigate to="/performance" replace />} />
        <Route path="/research/signals" element={<Navigate to="/scan" replace />} />
        <Route path="/execution" element={<Navigate to="/performance" replace />} />

        {/* Catch-all */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
