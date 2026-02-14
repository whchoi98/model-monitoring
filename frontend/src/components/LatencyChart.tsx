"use client";

import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import { ProbeResult } from "@/lib/types";

interface LatencyChartProps {
  results: ProbeResult[];
}

interface ModelAggregation {
  model: string;
  ttft_avg: number;
  latency_avg: number;
  server_avg: number;
  tps_avg: number;
}

function aggregateByModel(results: ProbeResult[]): ModelAggregation[] {
  const byModel = new Map<
    string,
    { ttfts: number[]; latencies: number[]; servers: number[]; tps: number[] }
  >();

  for (const r of results) {
    if (r.status !== "success") continue;
    const key = r.model_name;
    if (!byModel.has(key)) {
      byModel.set(key, { ttfts: [], latencies: [], servers: [], tps: [] });
    }
    const entry = byModel.get(key)!;
    if (r.ttft_ms !== null) entry.ttfts.push(r.ttft_ms);
    if (r.total_latency_ms !== null) entry.latencies.push(r.total_latency_ms);
    if (r.server_latency_ms !== null) entry.servers.push(r.server_latency_ms);
    if (r.tps !== null) entry.tps.push(r.tps);
  }

  const agg: ModelAggregation[] = [];
  byModel.forEach((vals, model) => {
    const avg = (arr: number[]) =>
      arr.length > 0 ? arr.reduce((s, v) => s + v, 0) / arr.length : 0;
    agg.push({
      model: model.length > 20 ? model.slice(0, 18) + "..." : model,
      ttft_avg: Math.round(avg(vals.ttfts)),
      latency_avg: Math.round(avg(vals.latencies)),
      server_avg: Math.round(avg(vals.servers)),
      tps_avg: parseFloat(avg(vals.tps).toFixed(1)),
    });
  });

  return agg.sort((a, b) => a.model.localeCompare(b.model));
}

const CustomTooltip = ({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) => {
  if (!active || !payload || payload.length === 0) return null;

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-3 shadow-xl">
      <p className="text-sm font-semibold text-gray-200 mb-2">{label}</p>
      {payload.map((entry, idx) => (
        <div key={idx} className="flex items-center gap-2 text-xs">
          <div
            className="w-2.5 h-2.5 rounded-sm"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-gray-400">{entry.name}:</span>
          <span className="text-gray-200 tabular-nums font-mono font-semibold">
            {entry.value}
            {entry.name === "TPS" ? " tok/s" : " ms"}
          </span>
        </div>
      ))}
    </div>
  );
};

export default function LatencyChart({ results }: LatencyChartProps) {
  const data = useMemo(() => aggregateByModel(results), [results]);

  if (data.length === 0) return null;

  return (
    <div className="space-y-6">
      {/* Latency Comparison Chart */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
          Latency Comparison (ms)
        </h3>
        <ResponsiveContainer width="100%" height={300}>
          <BarChart
            data={data}
            margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis
              dataKey="model"
              tick={{ fill: "#9ca3af", fontSize: 11 }}
              axisLine={{ stroke: "#374151" }}
              tickLine={{ stroke: "#374151" }}
            />
            <YAxis
              tick={{ fill: "#9ca3af", fontSize: 11 }}
              axisLine={{ stroke: "#374151" }}
              tickLine={{ stroke: "#374151" }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Legend
              wrapperStyle={{ fontSize: "12px", color: "#9ca3af" }}
            />
            <Bar
              dataKey="ttft_avg"
              name="TTFT"
              fill="#3b82f6"
              radius={[4, 4, 0, 0]}
              maxBarSize={60}
            />
            <Bar
              dataKey="server_avg"
              name="Server Latency"
              fill="#8b5cf6"
              radius={[4, 4, 0, 0]}
              maxBarSize={60}
            />
            <Bar
              dataKey="latency_avg"
              name="Total Latency"
              fill="#f59e0b"
              radius={[4, 4, 0, 0]}
              maxBarSize={60}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* TPS Comparison Chart */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-gray-400 uppercase tracking-wider mb-4">
          Throughput Comparison (tokens/sec)
        </h3>
        <ResponsiveContainer width="100%" height={250}>
          <BarChart
            data={data}
            margin={{ top: 5, right: 20, left: 10, bottom: 5 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis
              dataKey="model"
              tick={{ fill: "#9ca3af", fontSize: 11 }}
              axisLine={{ stroke: "#374151" }}
              tickLine={{ stroke: "#374151" }}
            />
            <YAxis
              tick={{ fill: "#9ca3af", fontSize: 11 }}
              axisLine={{ stroke: "#374151" }}
              tickLine={{ stroke: "#374151" }}
            />
            <Tooltip content={<CustomTooltip />} />
            <Bar
              dataKey="tps_avg"
              name="TPS"
              fill="#10b981"
              radius={[4, 4, 0, 0]}
              maxBarSize={80}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
