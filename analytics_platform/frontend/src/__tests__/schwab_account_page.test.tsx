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
    // Wait for data to load
    const tqqq = await screen.findByText("TQQQ");
    expect(tqqq).toBeInTheDocument();
    expect(screen.getByText("SOXL")).toBeInTheDocument();
    expect(screen.getByText("BIL")).toBeInTheDocument();
  });
});
