"use client";

import { useState } from "react";
import { ModelStats } from "@/lib/types";
import { fetchStats } from "@/lib/api";
import { useLang, useT } from "@/lib/i18n-context";
import { Translations } from "@/lib/i18n";
import { sortResults } from "@/lib/sortModels";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { DataEmpty, DataError, DataLoading } from "./DataState";
import Dialog from "./Dialog";
import RefreshControls from "./RefreshControls";

interface HistoryPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

type TimeRange = "5m" | "15m" | "30m" | "1h" | "6h" | "24h" | "7d" | "30d";

function getStartTime(range: TimeRange): string {
  const now = new Date();
  switch (range) {
    case "5m":
      return new Date(now.getTime() - 5 * 60 * 1000).toISOString();
    case "15m":
      return new Date(now.getTime() - 15 * 60 * 1000).toISOString();
    case "30m":
      return new Date(now.getTime() - 30 * 60 * 1000).toISOString();
    case "1h":
      return new Date(now.getTime() - 3600 * 1000).toISOString();
    case "6h":
      return new Date(now.getTime() - 6 * 3600 * 1000).toISOString();
    case "24h":
      return new Date(now.getTime() - 24 * 3600 * 1000).toISOString();
    case "7d":
      return new Date(now.getTime() - 7 * 24 * 3600 * 1000).toISOString();
    case "30d":
      return new Date(now.getTime() - 30 * 24 * 3600 * 1000).toISOString();
  }
}

type Measurement = number | null | undefined;

function formatMeasurement(value: Measurement, unit: string, decimals = 0): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `${value.toFixed(decimals)} ${unit}`;
}

function getTtftColor(ms: Measurement): string {
  if (ms == null || !Number.isFinite(ms)) return "text-gray-500";
  if (ms < 1000) return "text-emerald-400";
  if (ms < 3000) return "text-amber-400";
  return "text-rose-400";
}

function getLatencyColor(ms: Measurement): string {
  if (ms == null || !Number.isFinite(ms)) return "text-gray-500";
  if (ms < 2000) return "text-emerald-400";
  if (ms < 5000) return "text-amber-400";
  return "text-rose-400";
}

function getTpsColor(tps: Measurement): string {
  if (tps == null || !Number.isFinite(tps)) return "text-gray-500";
  if (tps > 50) return "text-emerald-400";
  if (tps > 20) return "text-amber-400";
  return "text-rose-400";
}

function getRegionBadge(name: string, t: Translations) {
  const region = name.match(/\(([^)]+)\)$/)?.[1];
  if (!region) return null;
  return (
    <span className={`inline-flex shrink-0 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${
      region === "Global"
        ? "border-blue-500/25 bg-blue-500/15 text-blue-400"
        : "border-amber-500/25 bg-amber-500/15 text-amber-400"
    }`}>
      {region === "Global" ? t.regionGlobal : region === "US" ? t.regionUS : region}
    </span>
  );
}

function MetricRow({ label, values, unit, color, decimals = 0 }: {
  label: string;
  values: [Measurement, Measurement, Measurement];
  unit: string;
  color: (value: Measurement) => string;
  decimals?: number;
}) {
  const t = useT();
  return (
    <div role="group" aria-label={label} className="min-w-0 space-y-1.5">
      <p className="text-xs font-medium text-gray-400">{label}</p>
      <dl className="grid grid-cols-3 gap-2 text-xs">
        {[t.avg, "p50", "p95"].map((name, index) => (
          <div key={name} className="min-w-0">
            <dt className="text-gray-500">{name}</dt>
            <dd className={`mt-0.5 break-words font-mono tabular-nums ${color(values[index])}`}>
              {formatMeasurement(values[index], unit, decimals)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function getTimeRanges(t: Translations): { value: TimeRange; label: string }[] {
  // i18n에 5m/15m/30m 키가 없어 fallback 문자열 사용 (한/영 모두 자연스러움).
  return [
    { value: "5m", label: "5m" },
    { value: "15m", label: "15m" },
    { value: "30m", label: "30m" },
    { value: "1h", label: t.range1h },
    { value: "6h", label: t.range6h },
    { value: "24h", label: t.range24h },
    { value: "7d", label: t.range7d },
    { value: "30d", label: t.range30d },
  ];
}

export default function HistoryPanel({ isOpen, onClose }: HistoryPanelProps) {
  // Keep the user's filters across close/reopen, but mount the resource only
  // while the dialog is open so hidden history never fetches.
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [selectedModels, setSelectedModels] = useState<Set<string>>(new Set());
  const toggleModel = (name: string) => {
    setSelectedModels((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };
  const clearSelection = () => setSelectedModels(new Set());

  if (!isOpen) return null;
  return (
    <OpenHistoryPanel
      onClose={onClose} timeRange={timeRange} onTimeRangeChange={setTimeRange}
      selectedModels={selectedModels} onToggleModel={toggleModel} onClearSelection={clearSelection}
    />
  );
}

function OpenHistoryPanel({ onClose, timeRange, onTimeRangeChange, selectedModels, onToggleModel, onClearSelection }: {
  onClose: () => void;
  timeRange: TimeRange;
  onTimeRangeChange: (range: TimeRange) => void;
  selectedModels: Set<string>;
  onToggleModel: (name: string) => void;
  onClearSelection: () => void;
}) {
  const t = useT();
  const { lang } = useLang();
  const resource = useAsyncResource<ModelStats[]>(
    `history:${timeRange}`,
    (signal) => fetchStats(getStartTime(timeRange), undefined, null, signal),
  );
  const sorted = sortResults(resource.data ?? []);
  const visible = selectedModels.size
    ? sorted.filter((s) => selectedModels.has(s.model_name))
    : sorted;
  const timeRanges = getTimeRanges(t);

  return (
    <Dialog title={t.historyTitle} onClose={onClose} className="max-w-4xl">
      <RefreshControls
        refreshing={resource.refreshing}
        onRefresh={() => { void resource.refresh(); }}
        updatedAt={resource.updatedAt}
      />
      <div role="group" aria-label={lang === "en" ? "Time range" : "조회 기간"} className="flex flex-wrap gap-2">
        {timeRanges.map((tr) => (
          <button
            key={tr.value} type="button" aria-pressed={timeRange === tr.value}
            onClick={() => onTimeRangeChange(tr.value)}
            className={timeRange === tr.value ? "ui-button-primary" : "ui-button"}
          >
            {tr.label}
          </button>
        ))}
      </div>

      {sorted.length > 0 && (
        <div role="group" aria-label={t.historyModelFilter} className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs font-semibold text-gray-500">{t.historyModelFilter}</span>
            <button type="button" onClick={onClearSelection} aria-pressed={selectedModels.size === 0}
              className={selectedModels.size === 0 ? "ui-button-primary" : "ui-button"}>
              {t.allModels}
            </button>
            {selectedModels.size > 0 && (
              <span className="text-xs text-gray-500">{t.monitoring.selection(selectedModels.size)}</span>
            )}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {sorted.map((s) => (
              <button key={s.model_id} type="button" onClick={() => onToggleModel(s.model_name)}
                aria-pressed={selectedModels.has(s.model_name)}
                className={`max-w-full break-words text-left ${selectedModels.has(s.model_name) ? "ui-button-primary" : "ui-button"}`}>
                {s.model_name}
              </button>
            ))}
          </div>
        </div>
      )}

      <DataError error={resource.error} resource={t.historyTitle}
        onRetry={() => { void resource.refresh(); }} hasData={resource.data !== null} />
      {resource.loading && <DataLoading />}
      {visible.length > 0 && (
        <div className="grid min-w-0 grid-cols-1 gap-4 md:grid-cols-2">
          {visible.map((s) => (
            <article key={s.model_id} aria-label={s.model_name}
              className="min-w-0 rounded-xl border border-gray-800 bg-gray-900/50">
              <div className="space-y-2 border-b border-gray-800/50 px-4 py-3">
                <h3 className="break-words text-sm font-semibold text-gray-200">{s.model_name}</h3>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  {getRegionBadge(s.model_name, t)}
                  <span className="text-xs tabular-nums text-gray-500">{s.count}{t.historyProbes}</span>
                </div>
              </div>
              <div className="min-w-0 space-y-3 px-4 py-3">
                <MetricRow label="TTFT" unit="ms" color={getTtftColor}
                  values={[s.avg_ttft_ms, s.p50_ttft_ms, s.p95_ttft_ms]} />
                <MetricRow label="Latency" unit="ms" color={getLatencyColor}
                  values={[s.avg_latency_ms, s.p50_latency_ms, s.p95_latency_ms]} />
                <MetricRow label="TPS" unit="tok/s" decimals={1} color={getTpsColor}
                  values={[s.avg_tps, s.p50_tps, s.p95_tps]} />
              </div>
            </article>
          ))}
        </div>
      )}
      {!resource.error && !resource.refreshing && resource.data !== null && visible.length === 0 && (
        <DataEmpty title={sorted.length === 0 ? t.historyNoData : t.common.noData}>
          {selectedModels.size > 0 && (
            <button type="button" className="ui-button" onClick={onClearSelection}>{t.common.resetFilters}</button>
          )}
        </DataEmpty>
      )}
    </Dialog>
  );
}
