/**
 * CandlestickChart — lightweight-charts v5 wrapper for scan detail panel.
 * Shows candlesticks + AVWAP line + horizontal price level markers.
 */
import { useEffect, useRef } from "react";
import {
  createChart,
  type IChartApi,
  type CandlestickData,
  type LineData,
  CandlestickSeries,
  LineSeries,
  ColorType,
  LineStyle,
  type Time,
} from "lightweight-charts";

export interface CandlePoint {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
}

export interface LinePoint {
  time: string;
  value: number;
}

export interface PriceLevel {
  price: number;
  color: string;
  label: string;
}

interface Props {
  candles: CandlePoint[];
  avwap?: LinePoint[];
  levels?: PriceLevel[];
  height?: number;
}

export function CandlestickChart({ candles, avwap, levels, height = 300 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!containerRef.current || candles.length === 0) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8b8fa3",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: "rgba(139, 143, 163, 0.08)" },
        horzLines: { color: "rgba(139, 143, 163, 0.08)" },
      },
      crosshair: {
        vertLine: { labelVisible: false },
      },
      rightPriceScale: {
        borderVisible: false,
      },
      timeScale: {
        borderVisible: false,
        timeVisible: false,
      },
    });
    chartRef.current = chart;

    // Candlestick series (v5 API)
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderDownColor: "#ef4444",
      borderUpColor: "#22c55e",
      wickDownColor: "#ef4444",
      wickUpColor: "#22c55e",
    });
    candleSeries.setData(candles as CandlestickData<Time>[]);

    // AVWAP line
    if (avwap && avwap.length > 0) {
      const lineSeries = chart.addSeries(LineSeries, {
        color: "#3b82f6",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      lineSeries.setData(avwap as LineData<Time>[]);
    }

    // Horizontal price levels
    if (levels) {
      for (const level of levels) {
        if (level.price > 0) {
          candleSeries.createPriceLine({
            price: level.price,
            color: level.color,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title: level.label,
          });
        }
      }
    }

    chart.timeScale().fitContent();

    // Resize observer
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [candles, avwap, levels, height]);

  if (candles.length === 0) {
    return (
      <div
        className="flex items-center justify-center text-xs text-vantage-muted"
        style={{ height }}
      >
        No chart data available
      </div>
    );
  }

  return <div ref={containerRef} style={{ height }} />;
}
