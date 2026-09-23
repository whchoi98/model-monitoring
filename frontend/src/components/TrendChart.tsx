"use client";

import { Fragment, memo, useMemo } from "react";
import { TrendPoint } from "@/lib/types";
import { isolatedSampleTimes, pivotTrend } from "@/lib/pivotTrend";
import { useChartTheme } from "@/lib/chartTheme";
import { useTheme } from "@/lib/theme";
import { useLang, useT } from "@/lib/i18n-context";
import { formatDateTime } from "@/lib/format";
import { channelRank } from "@/lib/sortModels";
import { DataEmpty } from "./DataState";
import {
  Area,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface Props {
  data: TrendPoint[];
  metric: "ttft_ms" | "total_latency_ms" | "tps";
  title: string;
  /** 선택된 모델 set (빈 set이면 전체 표시). 다중 비교 지원. */
  selectedModels?: Set<string>;
  /** 범례 클릭으로 모델 라인을 토글 (v2.7.1). */
  onToggleModel?: (modelName: string) => void;
  cadenceSeconds?: number;
}

// Backend는 "Bedrock <family> (channel)" 또는 "Anthropic <family> (US)" prefix가 붙은 model_name으로 응답.
// 매칭 안 되면 family substring 기반 fallback.
const MODEL_COLORS: Record<string, string> = {
  "Bedrock Claude Fable 5.1 (Global)": "#7dd3fc",
  "Bedrock Claude Fable 5.1 (US)": "#0ea5e9",
  "Bedrock Claude Fable 5 (Global)": "#2dd4bf",
  "Bedrock Claude Fable 5 (US)": "#0d9488",
  "Bedrock Claude Opus 5.5 (Global)": "#ff8fab",
  "Bedrock Claude Opus 5.5 (US)": "#e5383b",
  "Bedrock Claude Opus 5 (Global)": "#f43f5e",
  "Bedrock Claude Opus 5 (US)": "#be123c",
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
  "Anthropic Claude Fable 5.1 (US)": "#0369a1",
  "Anthropic Claude Fable 5 (US)": "#115e59",
  "Anthropic Claude Opus 5.5 (US)": "#a4161a",
  "Anthropic Claude Opus 5 (US)": "#881337",
  "Anthropic Claude Opus 4.8 (US)": "#9f1239",
  "Anthropic Claude Opus 4.7 (US)": "#7c3aed",
  "Anthropic Claude Sonnet 5 (US)": "#4338ca",
  "Anthropic Claude Sonnet 4.6 (US)": "#9333ea",
  "Anthropic Claude Haiku 4.5 (US)": "#d946ef",
  // GPT 6 Astra (v2.25.0) — Global CRIS / US CRIS / us-west-2 인리전 3채널.
  "OpenAI GPT 6 Astra (Global)": "#099268",
  "OpenAI GPT 6 Astra (US)": "#2e8b57",
  "OpenAI GPT 6 Astra (us-west-2)": "#2f855a",
  // GPT 6 Sol / Luna (v2.27.0) — Global CRIS / US CRIS / us-east-1 인리전 3채널씩.
  "OpenAI GPT 6 Sol (Global)": "#20c997",
  "OpenAI GPT 6 Sol (US)": "#12b886",
  "OpenAI GPT 6 Sol (us-east-1)": "#0ca678",
  "OpenAI GPT 6 Luna (Global)": "#96f2d7",
  "OpenAI GPT 6 Luna (US)": "#63e6be",
  "OpenAI GPT 6 Luna (us-east-1)": "#38d9a9",
  "OpenAI GPT 5.6 Sol (Global)": "#00fa9a",
  "OpenAI GPT 5.6 Sol (us-east-1)": "#22c55e",
  "OpenAI GPT 5.6 Sol (us-east-2)": "#16a34a",
  "OpenAI GPT 5.6 Sol (1P)": "#15803d",
  "OpenAI GPT 5.6 Terra (Global)": "#bef264",
  "OpenAI GPT 5.6 Terra (us-east-1)": "#a3e635",
  "OpenAI GPT 5.6 Terra (us-east-2)": "#65a30d",
  "OpenAI GPT 5.6 Terra (us-west-2)": "#4d7c0f",
  "OpenAI GPT 5.6 Terra (1P)": "#3f6212",
  "OpenAI GPT 5.6 Luna (Global)": "#5eead4",
  "OpenAI GPT 5.6 Luna (us-east-1)": "#4ade80",
  "OpenAI GPT 5.6 Luna (us-east-2)": "#14b8a6",
  "OpenAI GPT 5.6 Luna (us-west-2)": "#86efac",
  "OpenAI GPT 5.6 Luna (1P)": "#0f766e",
  "OpenAI GPT 5.5 (us-east-1)": "#10a37f",
  "OpenAI GPT 5.5 (us-east-2)": "#0d8a6a",
  "OpenAI GPT 5.5 (1P)": "#047857",
  "OpenAI GPT 5.4 (us-east-1)": "#34d399",
  "OpenAI GPT 5.4 (us-east-2)": "#059669",
  "OpenAI GPT 5.4 (us-west-2)": "#10b981",
  "OpenAI GPT 5.4 (1P)": "#6ee7b7",
};

// ⚠️ includes 매칭 — "Fable 5"는 "Fable 5.1"에, "Opus 5"는 "Opus 5.5"에도 포함되므로 긴 이름이 먼저 와야 함.
const FAMILY_FALLBACK: [string, string][] = [
  ["Fable 5.1", "#0ea5e9"],
  ["Fable 5", "#0d9488"],
  ["Opus 5.5", "#e5383b"],
  ["Opus 5", "#f43f5e"],
  ["Opus 4.8", "#e11d48"],
  ["Opus 4.7", "#ef4444"],
  ["Opus 4.6", "#f59e0b"],
  ["Sonnet 5", "#4f46e5"],
  ["Sonnet 4.6", "#8b5cf6"],
  ["Haiku 4.5", "#06b6d4"],
  ["Nova", "#84cc16"],
  ["GPT 6 Astra", "#2e8b57"],
  ["GPT 6 Sol", "#12b886"],
  ["GPT 6 Luna", "#63e6be"],
  ["GPT 5.6 Sol", "#22c55e"],
  ["GPT 5.6 Terra", "#a3e635"],
  ["GPT 5.6 Luna", "#4ade80"],
  ["GPT 5.5", "#10a37f"],
  ["GPT 5.4", "#34d399"],
];

function getColor(modelName: string, theme: "dark" | "light"): string {
  const base = MODEL_COLORS[modelName] ?? FAMILY_FALLBACK.find(([family]) => modelName.includes(family))?.[1] ?? "#9ca3af";
  const rgb = [1, 3, 5].map((index) => parseInt(base.slice(index, index + 2), 16));
  const brightness = rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114;
  // Keep pale lines visible on white cards and dark channel colors visible on dark cards.
  const adjusted = theme === "light" && brightness > 150 ? rgb.map((value) => Math.round(value * 0.62))
    : theme === "dark" && brightness < 110 ? rgb.map((value) => Math.round(value + (255 - value) * 0.3)) : rgb;
  return `#${adjusted.map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function formatUnit(value: number, metric: string): string {
  if (metric === "tps") return `${value.toFixed(1)} tok/s`;
  if (metric === "total_latency_ms") return `${(value / 1000).toFixed(1)}s`;
  return `${value.toFixed(0)} ms`;
}

function TrendChart({ data, metric, title, selectedModels, onToggleModel, cadenceSeconds }: Props) {
  const ct = useChartTheme();
  const theme = useTheme();
  const t = useT();
  const { lang } = useLang();
  const hasSelection = selectedModels && selectedModels.size > 0;
  // min–max 밴드: 단일 모델 선택 + 집계 구간(hours>24)일 때만 — 다중 모델 밴드는 시각적 혼잡.
  const showBand = selectedModels?.size === 1;

  // 피벗은 O(N) 단일 패스 (lib/pivotTrend). 칩 토글·자동새로고침마다 재실행되므로 useMemo 필수.
  const { modelNames, chartData, seriesData } = useMemo(
    () => pivotTrend(data, metric, selectedModels, { withRange: showBand, cadenceSeconds }),
    [data, metric, selectedModels, showBand, cadenceSeconds],
  );
  const hasRange =
    showBand && chartData.some((row) => row[`${modelNames[0]}__range`] !== undefined);

  // 포인트가 많으면 dot SVG 노드(포인트당 1개)가 렌더링을 지배 — 700개 초과 시 라인만 그린다.
  const totalPoints = Object.values(seriesData).reduce((sum, points) => sum + points.length, 0);
  const showDots = totalPoints <= 700;
  const measuredPoints = modelNames.reduce((sum, name) => sum + seriesData[name].filter((row) => typeof row[name] === "number").length, 0);
  const spansDays = chartData.length > 1 && new Date(chartData[0].time).toDateString() !== new Date(chartData[chartData.length - 1].time).toDateString();
  const timeFormatter = new Intl.DateTimeFormat(lang === "ko" ? "ko-KR" : "en-US", {
    ...(spansDays ? { month: "numeric", day: "numeric" } as const : {}),
    hour: "2-digit", minute: "2-digit", hour12: false,
  });

  if (data.length === 0) return null;

  if (chartData.length === 0) {
    return (
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
        <h3 className="text-sm font-semibold text-gray-200 mb-2">{title}</h3>
        <DataEmpty title={t.monitoring.noTrend} description={t.monitoring.noTrendHint} />
      </div>
    );
  }

  return (
    <figure aria-label={title} className="min-w-0 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-4">
        <h3 className="text-sm font-semibold text-gray-200">{title}</h3>
        <span className="text-xs tabular-nums text-gray-500">
          {hasSelection ? `${t.monitoring.selection(selectedModels!.size)} · ` : ""}
          {metric === "tps" ? "tok/s" : metric === "total_latency_ms" ? "s" : "ms"}
        </span>
      </div>
      {measuredPoints === 0 ? <DataEmpty title={t.monitoring.noMetric} description={t.monitoring.noMetricHint} /> : (
      <ResponsiveContainer width="100%" height={280}>
        <ComposedChart accessibilityLayer data={chartData} margin={{ top: 10, right: 8, bottom: 5, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={ct.grid} />
          <XAxis
            dataKey="time"
            type="number"
            scale="time"
            domain={chartData.length === 1 ? [chartData[0].time - 30_000, chartData[0].time + 30_000] : ["dataMin", "dataMax"]}
            allowDuplicatedCategory={false}
            tickFormatter={(value: number) => timeFormatter.format(value)}
            minTickGap={24}
            tickCount={5}
            tick={{ fill: ct.tick, fontSize: 11 }}
            stroke={ct.axisLine}
          />
          <YAxis
            width={52}
            tick={{ fill: ct.tick, fontSize: 11 }}
            stroke={ct.axisLine}
            tickFormatter={(v) => {
              if (metric === "tps") return v.toFixed(0);
              if (metric === "total_latency_ms") return `${(v / 1000).toFixed(1)}s`;
              return `${v.toFixed(0)}`;
            }}
          />
          <Tooltip
            contentStyle={ct.tooltipStyle}
            labelStyle={ct.tooltipLabel}
            labelFormatter={(value) => formatDateTime(Number(value), lang)}
            formatter={(value: number, name: string) => [
              formatUnit(value, metric),
              name,
            ]}
          />
          {/* min–max 밴드 — 시간 평균에 숨는 스파이크 노출 (범례에는 미표시) */}
          {hasRange && (
            <Area
              data={seriesData[modelNames[0]]}
              dataKey={`${modelNames[0]}__range`}
              stroke="none"
              fill={getColor(modelNames[0], theme)}
              fillOpacity={0.15}
              legendType="none"
              tooltipType="none"
              connectNulls={false}
              isAnimationActive={false}
            />
          )}
          {modelNames.map((name) => {
            const isolated = isolatedSampleTimes(seriesData[name], name);
            const stroke = getColor(name, theme);
            return (
            <Line
              key={name}
              data={seriesData[name]}
              type="monotone"
              dataKey={name}
              stroke={stroke}
              strokeDasharray={channelRank(name) === 0 ? "2 3" : channelRank(name) === 2 ? "6 3" : undefined}
              strokeWidth={2}
              dot={showDots ? { r: 3 } : ({ key, cx, cy, payload }: { key?: string; cx?: number; cy?: number; payload?: { time: number } }) =>
                payload && isolated.has(payload.time) && Number.isFinite(cx) && Number.isFinite(cy)
                  ? <circle key={key} cx={cx} cy={cy} r={3} fill={stroke} />
                  : <Fragment key={key} />}
              activeDot={{ r: 5 }}
              connectNulls={false}
              isAnimationActive={false}
            />
            );
          })}
        </ComposedChart>
      </ResponsiveContainer>
      )}
      <div className="mt-3 flex max-h-32 flex-wrap gap-x-3 gap-y-1 overflow-auto border-t border-gray-800 pt-3">
        {modelNames.map((name) => (
          <button type="button" key={name} onClick={() => onToggleModel?.(name)}
            aria-pressed={selectedModels?.has(name) ?? false} disabled={!onToggleModel}
            className="inline-flex min-h-8 max-w-full items-center gap-2 rounded-md px-1 text-left text-xs text-gray-400 hover:bg-gray-800 hover:text-gray-200">
            <span aria-hidden="true" style={{ backgroundColor: getColor(name, theme) }} className="h-0.5 w-4 shrink-0" />
            <span className="break-words">{name}</span>
          </button>
        ))}
      </div>
      <figcaption className="mt-2 text-xs leading-relaxed text-gray-500">
        {hasRange ? t.monitoring.aggregationHint : measuredPoints === 1 ? t.monitoring.singlePoint : t.monitoring.noMetricHint}
      </figcaption>
    </figure>
  );
}

// data/selectedModels 참조가 같으면 재렌더 스킵 (부모의 무관한 state 변경 차단).
export default memo(TrendChart);
