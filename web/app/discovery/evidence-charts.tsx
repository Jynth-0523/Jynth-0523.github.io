"use client";
import { useEffect, useRef } from "react";
import type { DiscoveryResult } from "./workspace-types";

export type WalkForwardWindow = DiscoveryResult["validation"]["walkForward"]["periods"][number];

export function cumulativeWealth(windows: WalkForwardWindow[]) {
  let gross = 1;
  let net = 1;
  return [
    { date: "Start", gross, net },
    ...windows.map((window) => {
      gross *= 1 + window.grossReturn;
      net *= 1 + window.netReturn;
      return { date: window.testDate, gross, net };
    }),
  ];
}

export function WalkForwardWealthChart({ windows }: { windows: WalkForwardWindow[] }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const series = cumulativeWealth(windows);
    const draw = () => {
      const width = Math.max(260, canvas.getBoundingClientRect().width);
      const height = 190;
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      const context = canvas.getContext("2d");
      if (!context) return;
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
      context.clearRect(0, 0, width, height);
      const values = series.flatMap((point) => [point.gross, point.net]);
      let low = Math.min(...values, 1);
      let high = Math.max(...values, 1);
      const padding = Math.max(0.01, (high - low) * 0.14);
      low -= padding;
      high += padding;
      const left = 10;
      const right = width - 10;
      const top = 12;
      const bottom = height - 12;
      const x = (index: number) => left + (right - left) * index / Math.max(1, series.length - 1);
      const y = (value: number) => bottom - (bottom - top) * (value - low) / Math.max(1e-9, high - low);
      context.lineWidth = 1;
      context.strokeStyle = "#dedbd1";
      for (let row = 0; row < 4; row += 1) {
        const gridY = top + (bottom - top) * row / 3;
        context.beginPath();
        context.moveTo(left, gridY);
        context.lineTo(right, gridY);
        context.stroke();
      }
      const plot = (key: "gross" | "net", color: string, lineWidth: number) => {
        context.beginPath();
        series.forEach((point, index) => {
          const pointX = x(index);
          const pointY = y(point[key]);
          if (index === 0) context.moveTo(pointX, pointY);
          else context.lineTo(pointX, pointY);
        });
        context.strokeStyle = color;
        context.lineWidth = lineWidth;
        context.lineJoin = "round";
        context.lineCap = "round";
        context.stroke();
      };
      plot("gross", "#93a2a0", 1.5);
      plot("net", "#183f3a", 2.5);
    };
    draw();
    const observer = new ResizeObserver(draw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [windows]);

  const wealth = cumulativeWealth(windows);
  const final = wealth[wealth.length - 1];
  return (
    <div className="result-chart">
      <div className="result-chart-head"><div><span>OUT-OF-SAMPLE WEALTH</span><strong>Gross versus net</strong></div><div className="chart-legend"><span className="net">Net {(final.net - 1 >= 0 ? "+" : "")}{((final.net - 1) * 100).toFixed(2)}%</span><span className="gross">Gross {(final.gross - 1 >= 0 ? "+" : "")}{((final.gross - 1) * 100).toFixed(2)}%</span></div></div>
      <canvas ref={canvasRef} role="img" aria-label="Cumulative gross and net wealth across out-of-sample periods" />
      <div className="chart-axis"><span>{windows[0]?.testDate.slice(0, 7) ?? "—"}</span><span>{windows.at(-1)?.testDate.slice(0, 7) ?? "—"}</span></div>
    </div>
  );
}

export function RankICTimeline({ windows }: { windows: WalkForwardWindow[] }) {
  const maxAbsolute = Math.max(0.01, ...windows.map((window) => Math.abs(window.oosRankIC ?? 0)));
  const labelStep = Math.max(1, Math.ceil(windows.length / 12));
  return (
    <div className="result-chart">
      <div className="result-chart-head"><div><span>OOS RANKIC</span><strong>Signal by test period</strong></div><div className="chart-legend"><span className="positive">Positive</span><span className="negative">Negative</span></div></div>
      <div className="rankic-timeline" role="img" aria-label="Out-of-sample RankIC by test period">
        {windows.map((window, index) => {
          const value = window.oosRankIC;
          const magnitude = Math.max(2, Math.abs(value ?? 0) / maxAbsolute * 47);
          const showLabel = windows.length <= 18 || index % labelStep === 0 || index === windows.length - 1;
          return <div className="rankic-column" key={window.testDate} title={`${window.testDate}: ${value === null ? "No trade" : value.toFixed(4)}`}><div className="rankic-track"><i className={value === null ? "no-trade" : value >= 0 ? "positive" : "negative"} style={value === null ? undefined : value >= 0 ? { height: `${magnitude}%`, bottom: "50%" } : { height: `${magnitude}%`, top: "50%" }} /></div><span>{showLabel ? window.testDate.slice(5, 7) : ""}</span></div>;
        })}
      </div>
      <div className="chart-axis"><span>{windows[0]?.testDate.slice(0, 4) ?? "—"}</span><span>{windows.at(-1)?.testDate.slice(0, 4) ?? "—"}</span></div>
    </div>
  );
}

