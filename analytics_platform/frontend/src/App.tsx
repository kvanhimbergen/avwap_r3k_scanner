import { Navigate, Route, Routes } from "react-router-dom";

import { Layout } from "./components/Layout";
import { BacktestsPage } from "./pages/BacktestsPage";
import { DecisionsPage } from "./pages/DecisionsPage";
import { HelpPage } from "./pages/HelpPage";
import { JournalPage } from "./pages/JournalPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PnlPage } from "./pages/PnlPage";
import { RaecDashboardPage } from "./pages/RaecDashboardPage";
import { ReadinessPage } from "./pages/ReadinessPage";
import { RiskPage } from "./pages/RiskPage";
import { S2SignalsPage } from "./pages/S2SignalsPage";
import { StrategiesPage } from "./pages/StrategiesPage";

export function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<OverviewPage />} />
        <Route path="/strategies" element={<StrategiesPage />} />
        <Route path="/signals/s2" element={<S2SignalsPage />} />
        <Route path="/decisions" element={<DecisionsPage />} />
        <Route path="/risk" element={<RiskPage />} />
        <Route path="/backtests" element={<BacktestsPage />} />
        <Route path="/raec" element={<RaecDashboardPage />} />
        <Route path="/raec/readiness" element={<ReadinessPage />} />
        <Route path="/journal" element={<JournalPage />} />
        <Route path="/pnl" element={<PnlPage />} />
        <Route path="/help" element={<HelpPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}
