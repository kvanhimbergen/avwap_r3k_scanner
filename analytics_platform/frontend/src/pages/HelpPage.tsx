export function HelpPage() {
  return (
    <section>
      <h2 className="page-title">Help: Daily Operating Guide</h2>

      <div className="helper-card">
        <h3 className="helper-title">Recommended Daily Workflow (10-15 min)</h3>
        <p className="helper-text">
          1) Start on <strong>Overview</strong> to confirm system pulse. 2) Open <strong>Decisions</strong> if
          rejected or gate blocks are elevated. 3) Use <strong>S2 Signals</strong> to inspect dominant reason codes and
          symbol-level failures. 4) Check <strong>Risk</strong> for throttle and regime changes before adjusting any
          strategy parameters.
        </p>
      </div>

      <div className="table-card">
        <h3>Page-by-Page Purpose</h3>
        <table>
          <thead>
            <tr>
              <th>Page</th>
              <th>Use It For</th>
              <th>When To Act</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Overview</td>
              <td>Top-level health and trend check.</td>
              <td>Act if rejected/gate blocks spike relative to recent days.</td>
            </tr>
            <tr>
              <td>Strategies</td>
              <td>AVWAP vs S2 throughput and concentration comparison.</td>
              <td>Act if one strategy dominates exposure or symbol breadth collapses.</td>
            </tr>
            <tr>
              <td>S2 Signals</td>
              <td>Signal-level audit for S2 eligibility and selection logic.</td>
              <td>Act if one or two reason codes dominate for multiple sessions.</td>
            </tr>
            <tr>
              <td>Decisions</td>
              <td>Operational friction diagnostics (cycles, rejections, gate blocks).</td>
              <td>Act if cycles are stable but rejections trend up.</td>
            </tr>
            <tr>
              <td>Risk</td>
              <td>Risk multipliers, throttle events, and regime context.</td>
              <td>Act if risk multipliers stay compressed across sessions.</td>
            </tr>
            <tr>
              <td>Backtests</td>
              <td>Replay/backtest run comparison and equity-shape review.</td>
              <td>Act if live behavior diverges materially from selected run assumptions.</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="two-col">
        <div className="table-card">
          <h3>Weekly Review Routine</h3>
          <table>
            <tbody>
              <tr>
                <td>1</td>
                <td>Export key datasets (signals, decisions, rejections).</td>
              </tr>
              <tr>
                <td>2</td>
                <td>Rank top rejection reasons and affected symbols.</td>
              </tr>
              <tr>
                <td>3</td>
                <td>Compare AVWAP vs S2 acceptance and concentration drift.</td>
              </tr>
              <tr>
                <td>4</td>
                <td>Review risk throttle periods and regime transitions.</td>
              </tr>
              <tr>
                <td>5</td>
                <td>Make one controlled parameter change at most; monitor next week.</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div className="table-card">
          <h3>Quick Troubleshooting</h3>
          <table>
            <tbody>
              <tr>
                <td>Blank or stale charts</td>
                <td>Check <code>/api/v1/health</code> and <code>/api/v1/freshness</code>.</td>
              </tr>
              <tr>
                <td>Missing S2 rows</td>
                <td>Confirm STRATEGY_SIGNALS files exist for the expected date.</td>
              </tr>
              <tr>
                <td>No recent decisions</td>
                <td>Verify execution/runtime ledgers are being written.</td>
              </tr>
              <tr>
                <td>Low acceptance suddenly</td>
                <td>Inspect risk page first, then reason codes in S2 Signals.</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
