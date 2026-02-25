import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("../api", () => ({
  api: {
    tradeLogList: vi.fn().mockResolvedValue({
      data: { trades: [] },
    }),
    tradeLogSummary: vi.fn().mockResolvedValue({
      data: {
        open_count: 0,
        closed_count: 0,
        wins: 0,
        losses: 0,
        win_rate: null,
        avg_r_multiple: null,
        total_pnl: 0,
      },
    }),
    tradeLogCreate: vi.fn(),
    tradeLogClose: vi.fn(),
    tradeLogDelete: vi.fn(),
  },
}));

import { TradeLogPage } from "../pages/TradeLogPage";

describe("TradeLogPage", () => {
  it("renders heading", async () => {
    render(
      <MemoryRouter>
        <TradeLogPage />
      </MemoryRouter>,
    );
    expect(screen.getByRole("heading", { level: 2, name: "Trade Log" })).toBeInTheDocument();
  });

  it("shows empty state when no trades", async () => {
    render(
      <MemoryRouter>
        <TradeLogPage />
      </MemoryRouter>,
    );
    const msg = await screen.findByText(/No trades logged yet/);
    expect(msg).toBeInTheDocument();
  });
});
