import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

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
const SystemPage = lazy(() =>
  import("./pages/SystemPage").then((m) => ({ default: m.SystemPage })),
);

function PageFallback() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-8 w-48" />
      <div className="grid grid-cols-4 gap-4">
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
            <Suspense fallback={<PageFallback />}>
              <CommandCenter />
            </Suspense>
          }
        />
        <Route
          path="/strategies"
          element={
            <Suspense fallback={<PageFallback />}>
              <StrategyRoster />
            </Suspense>
          }
        />
        <Route
          path="/strategies/:id"
          element={
            <Suspense fallback={<PageFallback />}>
              <StrategyTearsheet />
            </Suspense>
          }
        />
        <Route
          path="/trade"
          element={
            <Suspense fallback={<PageFallback />}>
              <TradePage />
            </Suspense>
          }
        />
        <Route
          path="/lab"
          element={
            <Suspense fallback={<PageFallback />}>
              <StrategyLab />
            </Suspense>
          }
        />
        <Route
          path="/blotter"
          element={
            <Suspense fallback={<PageFallback />}>
              <BlotterPage />
            </Suspense>
          }
        />
        <Route
          path="/performance"
          element={
            <Suspense fallback={<PageFallback />}>
              <PerformancePage />
            </Suspense>
          }
        />
        <Route
          path="/risk"
          element={
            <Suspense fallback={<PageFallback />}>
              <RiskPage />
            </Suspense>
          }
        />
        <Route
          path="/scan"
          element={
            <Suspense fallback={<PageFallback />}>
              <ScanPage />
            </Suspense>
          }
        />
        <Route
          path="/trade-log"
          element={
            <Suspense fallback={<PageFallback />}>
              <TradeLogPage />
            </Suspense>
          }
        />
        <Route
          path="/ops"
          element={<Navigate to="/ops/schwab" replace />}
        />
        <Route
          path="/ops/schwab"
          element={
            <Suspense fallback={<PageFallback />}>
              <SchwabAccountPage />
            </Suspense>
          }
        />
        <Route
          path="/ops/system"
          element={
            <Suspense fallback={<PageFallback />}>
              <SystemPage />
            </Suspense>
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
