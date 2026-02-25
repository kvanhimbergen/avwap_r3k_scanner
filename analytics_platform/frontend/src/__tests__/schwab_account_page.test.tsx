import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api", () => ({
  api: {
    schwabOverview: vi.fn().mockResolvedValue({
      data: {
        latest_account: {
          ny_date: "2026-02-10",
          as_of_utc: "2026-02-10T16:00:00+00:00",
          cash: 5000,
          market_value: 20922.83,
          total_value: 25922.83,
        },
        balance_history: [],
        positions: [
          { symbol: "TQQQ", qty: 100, cost_basis: 6500, market_value: 7725, weight_pct: 36.9 },
          { symbol: "SOXL", qty: 50, cost_basis: 5000, market_value: 5200, weight_pct: 24.8 },
          { symbol: "BIL", qty: 200, cost_basis: 8000, market_value: 7997.83, weight_pct: 38.2 },
        ],
        positions_date: "2026-02-10",
        orders: [],
        latest_reconciliation: null,
      },
    }),
    schwabTradeInstructions: vi.fn().mockResolvedValue({
      data: {
        days: [
          {
            ny_date: "2026-02-10",
            intents: [
              { ny_date: "2026-02-10", strategy_id: "RAEC_401K_V3", intent_id: "i1", symbol: "TQQQ", side: "BUY", delta_pct: 5.0, target_pct: 40.0, current_pct: 35.0, dollar_amount: 1296, actionable: true },
            ],
            events: [
              { ny_date: "2026-02-10", strategy_id: "RAEC_401K_V3", regime: "RISK_ON", should_rebalance: true, intent_count: 1 },
            ],
            actionable_count: 1,
          },
        ],
        total_value: 25922.83,
        threshold_dollars: 250,
        threshold_pct: 0.5,
      },
    }),
  },
}));

import { SchwabAccountPage } from "../pages/SchwabAccountPage";

describe("SchwabAccountPage", () => {
  it("renders heading", async () => {
    render(
      <MemoryRouter>
        <SchwabAccountPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Schwab Account" })).toBeInTheDocument();
  });

  it("renders positions table", async () => {
    render(
      <MemoryRouter>
        <SchwabAccountPage />
      </MemoryRouter>,
    );
    // Wait for positions heading
    const heading = await screen.findByText(/^Positions \(/);
    expect(heading).toBeInTheDocument();
    // SOXL and BIL only appear in positions table (not in trade instructions mock)
    expect(screen.getByText("SOXL")).toBeInTheDocument();
    expect(screen.getByText("BIL")).toBeInTheDocument();
  });

  it("renders trade instructions panel with strategy name", async () => {
    render(
      <MemoryRouter>
        <SchwabAccountPage />
      </MemoryRouter>,
    );
    // Wait for Trade Instructions header to appear
    const header = await screen.findByText("Trade Instructions");
    expect(header).toBeInTheDocument();
    // Strategy short name V3 and subtitle Aggressive should render
    expect(await screen.findByText("V3")).toBeInTheDocument();
  });

  it("renders P&L columns in positions table", async () => {
    render(
      <MemoryRouter>
        <SchwabAccountPage />
      </MemoryRouter>,
    );
    // Wait for positions heading
    await screen.findByText(/^Positions \(/);
    expect(screen.getByText("P&L")).toBeInTheDocument();
    expect(screen.getByText("P&L %")).toBeInTheDocument();
  });
});
