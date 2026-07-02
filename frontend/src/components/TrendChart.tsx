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
  /** 선택된 모델 set (빈 set이면 전체 표시). 다중 비교 지원. */
  selectedModels?: Set<string>;
}

// Backend는 "Bedrock <family> (channel)" 또는 "Anthropic <family> (US)" prefix가 붙은 model_name으로 응답.
// 매칭 안 되면 family substring 기반 fallback.
const MODEL_COLORS: Record<string, string> = {
  "Bedrock Claude Fable 5 (Global)": "#2dd4bf",
  "Bedrock Claude Fable 5 (US)": "#0d9488",
  "Bedrock Claude Opus 4.8 (Global)": "#fb7185",
  "Bedrock Claude Opus 4.8 (US)": "#e11d48",
  "Bedrock Claude Opus 4.7 (Global)": "#f97316",
  "Bedrock Claude Opus 4.7 (US)": "#ef4444",
  "Bedrock Claude Opus 4.6 (Global)": "#f59e0b",
  "Bedrock Claude Opus 4.6 (US)": "#ec4899",
  "Bedrock Claude Sonnet 5 (Global)": "#6366f1",
  "Bedrock Claude Sonnet 5 (US)": "#4f46e5",
  "Bedrock Claude Sonnet 4.6 (Global)": "#3b82f6",
  "Bedrock Claude Sonnet 4.6 (US)": "#8b5cf6",
  "Bedrock Claude Haiku 4.5 (Global)": "#06b6d4",
  "Bedrock Claude Haiku 4.5 (US)": "#a855f7",
  "Bedrock Nova 2.0 Lite (US)": "#84cc16",
  "Anthropic Claude Fable 5 (US)": "#115e59",
  "Anthropic Claude Opus 4.8 (US)": "#9f1239",
  "Anthropic Claude Opus 4.7 (US)": "#7c3aed",
  "Anthropic Claude Sonnet 5 (US)": "#4338ca",
  "Anthropic Claude Sonnet 4.6 (US)": "#9333ea",
  "Anthropic Claude Haiku 4.5 (US)": "#d946ef",
  "OpenAI GPT 5.5 (us-east-1)": "#10a37f",
  "OpenAI GPT 5.5 (us-east-2)": "#0d8a6a",
  "OpenAI GPT 5.5 (1P)": "#047857",
  "OpenAI GPT 5.4 (us-east-1)": "#34d399",
  "OpenAI GPT 5.4 (us-east-2)": "#059669",
  "OpenAI GPT 5.4 (us-west-2)": "#10b981",
  "OpenAI GPT 5.4 (1P)": "#6ee7b7",
};

const FAMILY_FALLBACK: [string, string][] = [
  ["Fable 5", "#0d9488"],
  ["Opus 4.8", "#e11d48"],
  ["Opus 4.7", "#ef4444"],
  ["Opus 4.6", "#f59e0b"],
  ["Sonnet 5", "#4f46e5"],
  ["Sonnet 4.6", "#8b5cf6"],
  ["Haiku 4.5", "#06b6d4"],
  ["Nova", "#84cc16"],
  ["GPT 5.5", "#10a37f"],
  ["GPT 5.4", "#34d399"],
];

function getColor(modelName: string): string {
  if (MODEL_COLORS[modelName]) return MODEL_COLORS[modelName];
  for (const [fam, color] of FAMILY_FALLBACK) {
    if (modelName.includes(fam)) return color;
  }
  return "#9ca3af";
}

function formatUnit(value: number, metric: string): string {
  if (metric === "tps") return `${value.toFixed(1)} tok/s`;
  if (metric === "total_latency_ms") return `${(value / 1000).toFixed(1)}s`;
  return `${value.toFixed(0)} ms`;
}

export default function TrendChart({ data, metric, title, selectedModels }: Props) {
  if (data.length === 0) return null;

  const hasSelection = selectedModels && selectedModels.size > 0;
  const filtered = hasSelection
    ? data.filter((d) => selectedModels!.has(d.model_name))
    : data;

  if (filtered.length === 0) {
    const names = Array.from(selectedModels ?? []).join(", ");
    return (
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-2">{title}</h3>
        <p className="text-xs text-gray-500">
          선택한 모델({names})의 추세 데이터가 없습니다.
        </p>
      </div>
    );
  }

  const modelNames = Array.from(new Set(filtered.map((d) => d.model_name)));
  const timestamps = Array.from(new Set(filtered.map((d) => d.timestamp))).sort();

  const chartData = timestamps.map((ts) => {
    const point: Record<string, string | number | null> = {
      timestamp: ts,
      time: new Date(ts).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" }),
    };
    for (const name of modelNames) {
      const match = filtered.find((d) => d.timestamp === ts && d.model_name === name);
      point[name] = match ? match[metric] : null;
    }
    return point;
  });

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-gray-200">{title}</h3>
        {hasSelection && (
          <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30">
            🔍 {selectedModels!.size}개 선택
          </span>
        )}
      </div>
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
              if (metric === "tps") return v.toFixed(0);
              if (metric === "total_latency_ms") return `${(v / 1000).toFixed(1)}s`;
              return `${v.toFixed(0)}`;
            }}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#0f172a",
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
