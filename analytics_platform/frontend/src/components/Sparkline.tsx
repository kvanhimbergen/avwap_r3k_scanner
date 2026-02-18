/**
 * Pure SVG sparkline — no Recharts dependency.
 * Renders a tiny inline trend chart.
 * Memoized to avoid re-computing paths on unrelated re-renders.
 */
import { memo, useMemo } from "react";

export const Sparkline = memo(function Sparkline({
  data,
  width = 60,
  height = 20,
  color = "var(--blue)",
  showArea = true,
}: {
  data: number[];
  width?: number;
  height?: number;
  color?: string;
  showArea?: boolean;
}) {
  const { linePath, areaPath } = useMemo(() => {
    if (data.length < 2) return { linePath: "", areaPath: "" };

    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const pad = 1;

    const points = data.map((v, i) => {
      const x = (i / (data.length - 1)) * (width - pad * 2) + pad;
      const y = height - pad - ((v - min) / range) * (height - pad * 2);
      return `${x},${y}`;
    });

    const line = `M${points.join(" L")}`;
    const area = `${line} L${width - pad},${height - pad} L${pad},${height - pad} Z`;
    return { linePath: line, areaPath: area };
  }, [data, width, height]);

  if (!linePath) {
    return (
      <svg
        className="sparkline"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
      />
    );
  }

  return (
    <svg
      className="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
    >
      {showArea && (
        <path className="sparkline-area" d={areaPath} fill={color} />
      )}
      <path className="sparkline-line" d={linePath} stroke={color} />
    </svg>
  );
});
