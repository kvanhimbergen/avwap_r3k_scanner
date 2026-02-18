/**
 * Reverse-chronological activity feed for the Command Center.
 * Shows regime changes, rebalances, fills, scan events.
 */

export interface FeedEvent {
  time: string;
  type: "regime-change" | "rebalance" | "fill" | "scan" | "gate-block" | "info";
  strategyId?: string;
  text: string;
}

const TYPE_ICON: Record<string, string> = {
  "regime-change": "\u25C6",
  rebalance: "\u21BB",
  fill: "\u2713",
  scan: "\u25B6",
  "gate-block": "\u2298",
  info: "\u25CF",
};

export function ActivityFeed({ events }: { events: FeedEvent[] }) {
  return (
    <div className="data-card">
      <h3 style={{ margin: "0 0 8px", fontSize: "0.82rem", fontWeight: 600, color: "var(--text)" }}>
        Activity
      </h3>
      {events.length === 0 ? (
        <div className="empty-state" style={{ padding: "16px 0" }}>
          <div style={{ fontSize: "0.78rem", color: "var(--text-tertiary)" }}>No recent activity</div>
        </div>
      ) : (
        <div className="feed">
          {events.map((event, i) => (
            <div key={i} className="feed-entry">
              <span className="feed-time">{event.time}</span>
              <span className="feed-icon">{TYPE_ICON[event.type] ?? "\u25CF"}</span>
              <span className="feed-text">
                {event.strategyId && (
                  <span className="feed-strategy" style={{ marginRight: 4 }}>
                    {event.strategyId}
                  </span>
                )}
                {event.text}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
