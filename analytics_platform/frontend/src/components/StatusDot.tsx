export type StatusLevel = "ok" | "warn" | "error" | "neutral";

export function StatusDot({
  status,
  large,
}: {
  status: StatusLevel;
  large?: boolean;
}) {
  return (
    <span
      className={`status-dot ${status}${large ? " status-dot-lg" : ""}`}
      title={status}
    />
  );
}
