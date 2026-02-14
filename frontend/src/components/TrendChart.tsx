"use client";

import { TrendPoint } from "@/lib/types";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";

interface Props {
  data: TrendPoint[];
  metric: "ttft_ms" | "total_latency_ms" | "tps";
  title: string;
}

const MODEL_COLORS: Record<string, string> = {
  "Claude Sonnet 4.5 (US)": "#3b82f6",
  "Claude Haiku 4.5 (US)": "#10b981",
  "Claude Opus 4.5 (US)": "#8b5cf6",
  "Claude Opus 4.6 (US)": "#f59e0b",
  "Claude Haiku 4.5 (Global)": "#06b6d4",
  "Claude Sonnet 4.5 (Global)": "#6366f1",
  "Claude Opus 4.5 (Global)": "#ec4899",
  "Claude Opus 4.6 (Global)": "#f97316",
  "Nova 2.0 Lite (US)": "#84cc16",
};

function getColor(modelName: string): string {
  return MODEL_COLORS[modelName] || "#9ca3af";
}

function formatUnit(value: number, metric: string): string {
  if (metric === "tps") return `${value.toFixed(1)} tok/s`;
  if (metric === "total_latency_ms") return `${(value / 1000).toFixed(1)}s`;
  return `${value.toFixed(0)} ms`;
}

export default function TrendChart({ data, metric, title }: Props) {
  if (data.length === 0) return null;

  // Get unique model names
  const modelNames = Array.from(new Set(data.map((d) => d.model_name)));

  // Get unique timestamps and build pivot table
  const timestamps = Array.from(new Set(data.map((d) => d.timestamp))).sort();

  const chartData = timestamps.map((ts) => {
    const point: Record<string, string | number | null> = {
      timestamp: ts,
      time: new Date(ts).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }),
    };
    for (const name of modelNames) {
      const match = data.find((d) => d.timestamp === ts && d.model_name === name);
      point[name] = match ? match[metric] : null;
    }
    return point;
  });

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-gray-200 mb-4">{title}</h3>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="time"
            tick={{ fill: "#6b7280", fontSize: 11 }}
            stroke="#374151"
          />
          <YAxis
            tick={{ fill: "#6b7280", fontSize: 11 }}
            stroke="#374151"
            tickFormatter={(v) => {
              if (metric === "total_latency_ms") return `${(v / 1000).toFixed(0)}s`;
              if (metric === "tps") return `${v}`;
              return `${v}`;
            }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#111827",
              border: "1px solid #374151",
              borderRadius: "8px",
              fontSize: "12px",
            }}
            labelStyle={{ color: "#9ca3af" }}
            formatter={(value: number, name: string) => [
              formatUnit(value, metric),
              name,
            ]}
          />
          <Legend
            wrapperStyle={{ fontSize: "11px", paddingTop: "8px" }}
          />
          {modelNames.map((name) => (
            <Line
              key={name}
              type="monotone"
              dataKey={name}
              stroke={getColor(name)}
              strokeWidth={2}
              dot={{ r: 3 }}
              activeDot={{ r: 5 }}
              connectNulls
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
