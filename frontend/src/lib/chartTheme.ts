// Recharts는 SVG 속성에 JS 상수 색상을 쓰므로 CSS 변수를 직접 못 받는다 —
// useTheme()로 분기하는 테마별 차트 팔레트 (v2.8.0).
import type { CSSProperties } from "react";
import { useTheme } from "./theme";

export interface ChartTheme {
  grid: string;
  axisLine: string;
  tick: string;
  tooltipStyle: CSSProperties;
  tooltipLabel: CSSProperties;
}

const DARK: ChartTheme = {
  grid: "#1f2937",
  axisLine: "#374151",
  tick: "#6b7280",
  tooltipStyle: {
    backgroundColor: "#0f172a",
    border: "1px solid #374151",
    borderRadius: "8px",
    fontSize: "12px",
  },
  tooltipLabel: { color: "#9ca3af" },
};

const LIGHT: ChartTheme = {
  grid: "#e2e8f0",
  axisLine: "#cbd5e1",
  tick: "#64748b",
  tooltipStyle: {
    backgroundColor: "#ffffff",
    border: "1px solid #e2e8f0",
    borderRadius: "8px",
    fontSize: "12px",
    boxShadow: "0 4px 12px rgb(15 23 42 / 0.08)",
  },
  tooltipLabel: { color: "#475569" },
};

export function useChartTheme(): ChartTheme {
  return useTheme() === "light" ? LIGHT : DARK;
}
