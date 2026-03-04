import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api", () => ({
  api: {
    rebalanceDashboard: vi.fn().mockResolvedValue({
      data: {
        token_health: { healthy: true, days_until_expiry: 5.2, reason: null },
        portfolio_value: 26500,
        positions_date: "2026-02-11",
        strategies: [
          {
            id: "RAEC_401K_V3",
            label: "V3",
            weight: 0.4,
            regime: "RISK_ON",
            smoothed_regime: "RISK_ON",
            targets: { TQQQ: 35.0, SOXL: 25.0, BIL: 40.0 },
            last_rebalance_date: "2026-02-10",
            cooldown_days_remaining: 0,
          },
          {
            id: "RAEC_401K_V4",
            label: "V4",
            weight: 0.3,
            regime: "TRANSITION",
            smoothed_regime: "TRANSITION",
            targets: { GLD: 30.0, IEF: 40.0, BIL: 30.0 },
            last_rebalance_date: "2026-02-10",
            cooldown_days_remaining: 0,
          },
          {
            id: "RAEC_401K_V5",
            label: "V5",
            weight: 0.3,
            regime: "RISK_ON",
            smoothed_regime: "RISK_ON",
            targets: { SMH: 50.0, BIL: 30.0, SOXL: 20.0 },
            last_rebalance_date: "2026-02-10",
            cooldown_days_remaining: 0,
          },
        ],
        combined_target: { TQQQ: 14.0, SOXL: 16.0, BIL: 34.0, GLD: 9.0, IEF: 12.0, SMH: 15.0 },
        current_positions: [
          { symbol: "TQQQ", weight_pct: 36.9, market_value: 7725 },
          { symbol: "SOXL", weight_pct: 24.8, market_value: 5200 },
          { symbol: "BIL", weight_pct: 38.2, market_value: 7997.83 },
        ],
        trades: [
          { symbol: "TQQQ", side: "SELL", current_pct: 36.9, target_pct: 14.0, delta_pct: -22.9, dollar_amount: 6068, actionable: true },
          { symbol: "SMH", side: "BUY", current_pct: 0.0, target_pct: 15.0, delta_pct: 15.0, dollar_amount: 3975, actionable: true },
          { symbol: "GLD", side: "BUY", current_pct: 0.0, target_pct: 9.0, delta_pct: 9.0, dollar_amount: 2385, actionable: true },
        ],
        last_sync_date: "2026-02-11",
      },
    }),
  },
}));

import { RebalancePage } from "../pages/RebalancePage";

describe("RebalancePage", () => {
  it("renders heading", async () => {
    render(
      <MemoryRouter>
        <RebalancePage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Rebalance Dashboard" })).toBeInTheDocument();
  });

  it("renders trade recommendations table", async () => {
    render(
      <MemoryRouter>
        <RebalancePage />
      </MemoryRouter>,
    );
    const header = await screen.findByText("Trade Recommendations");
    expect(header).toBeInTheDocument();
    // Trade table should show side badges — BUY and SELL
    const buyBadges = await screen.findAllByText("BUY");
    expect(buyBadges.length).toBeGreaterThanOrEqual(1);
    const sellBadges = await screen.findAllByText("SELL");
    expect(sellBadges.length).toBeGreaterThanOrEqual(1);
  });

  it("renders strategy cards with regime badges", async () => {
    render(
      <MemoryRouter>
        <RebalancePage />
      </MemoryRouter>,
    );
    // Strategy short names
    expect(await screen.findByText("V3")).toBeInTheDocument();
    expect(await screen.findByText("V4")).toBeInTheDocument();
    expect(await screen.findByText("V5")).toBeInTheDocument();
  });

  it("renders KPI cards", async () => {
    render(
      <MemoryRouter>
        <RebalancePage />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Portfolio Value")).toBeInTheDocument();
    expect(await screen.findByText("Trades Needed")).toBeInTheDocument();
    expect(await screen.findByText("Token Expiry")).toBeInTheDocument();
  });
});
