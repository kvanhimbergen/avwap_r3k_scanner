/**
 * Reverse-chronological activity feed for the Command Center.
 * Shows regime changes, rebalances, fills, scan events.
 */
import type { LucideIcon } from "lucide-react";
import { Diamond, RefreshCw, CheckCircle, Play, Ban, Circle } from "../icons";

export interface FeedEvent {
  time: string;
  type: "regime-change" | "rebalance" | "fill" | "scan" | "gate-block" | "info";
  strategyId?: string;
  text: string;
}

const TYPE_ICON: Record<string, LucideIcon> = {
  "regime-change": Diamond,
  rebalance: RefreshCw,
  fill: CheckCircle,
  scan: Play,
  "gate-block": Ban,
  info: Circle,
};

export function ActivityFeed({ events }: { events: FeedEvent[] }) {
  return (
    <div className="data-card">
      <div className="section-header">
        <h3 className="section-header-title">Activity</h3>
        {events.length > 0 && (
          <span className="section-header-count">{events.length}</span>
        )}
      </div>
      {events.length === 0 ? (
        <div className="empty-state" style={{ padding: "16px 0" }}>
          <div style={{ fontSize: "0.78rem", color: "var(--text-tertiary)" }}>No recent activity</div>
        </div>
      ) : (
        <div className="feed">
          {events.map((event, i) => {
            const Icon = TYPE_ICON[event.type] ?? Circle;
            return (
              <div key={i} className="feed-entry">
                <span className="feed-time">{event.time}</span>
                <span className="feed-icon">
                  <Icon size={13} strokeWidth={1.75} />
                </span>
                <span className="feed-text">
                  {event.strategyId && (
                    <span className="feed-strategy" style={{ marginRight: 4 }}>
                      {event.strategyId}
                    </span>
                  )}
                  {event.text}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
