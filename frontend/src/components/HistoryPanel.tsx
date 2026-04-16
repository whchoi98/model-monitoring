"use client";

import { useState, useEffect, useCallback } from "react";
import { ModelStats } from "@/lib/types";
import { fetchStats } from "@/lib/api";
import { useT } from "@/lib/i18n-context";
import { Translations } from "@/lib/i18n";

interface HistoryPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

type TimeRange = "1h" | "6h" | "24h" | "7d" | "30d";

function getStartTime(range: TimeRange): string {
  const now = new Date();
  switch (range) {
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

function formatNum(val: number | null, decimals: number = 0): string {
  if (val === null || val === undefined) return "-";
  return val.toFixed(decimals);
}

function getTtftColor(ms: number | null): string {
  if (ms === null) return "text-gray-500";
  if (ms < 1000) return "text-emerald-400";
  if (ms < 3000) return "text-amber-400";
  return "text-rose-400";
}

function getLatencyColor(ms: number | null): string {
  if (ms === null) return "text-gray-500";
  if (ms < 2000) return "text-emerald-400";
  if (ms < 5000) return "text-amber-400";
  return "text-rose-400";
}

function getTpsColor(tps: number | null): string {
  if (tps === null) return "text-gray-500";
  if (tps > 50) return "text-emerald-400";
  if (tps > 20) return "text-amber-400";
  return "text-rose-400";
}

function isGlobal(name: string): boolean {
  return name.includes("(Global)");
}

/** Sort key: [regionOrder, -version, tierOrder] — same logic as ModelStatusGrid */
function modelSortKey(name: string): [number, number, number] {
  const regionOrder = name.includes("(Global)") ? 0 : name.includes("(US)") ? 1 : 2;
  const verMatch = name.match(/(\d+\.\d+)/);
  const version = verMatch ? parseFloat(verMatch[1]) : 0;
  const tierOrder = name.includes("Opus") ? 0 : name.includes("Sonnet") ? 1 : name.includes("Haiku") ? 2 : 3;
  return [regionOrder, -version, tierOrder];
}

function sortStats(stats: ModelStats[]): ModelStats[] {
  return [...stats].sort((a, b) => {
    const ka = modelSortKey(a.model_name);
    const kb = modelSortKey(b.model_name);
    for (let i = 0; i < ka.length; i++) {
      if (ka[i] !== kb[i]) return ka[i] - kb[i];
    }
    return 0;
  });
}

function getRegionBadge(name: string, t: Translations) {
  if (isGlobal(name)) {
    return (
      <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-blue-500/15 text-blue-400 border border-blue-500/25">
        {t.regionGlobal}
      </span>
    );
  }
  return (
    <span className="inline-flex px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-500/15 text-amber-400 border border-amber-500/25">
      {t.regionUS}
    </span>
  );
}

function getTimeRanges(t: Translations): { value: TimeRange; label: string }[] {
  return [
    { value: "1h", label: t.range1h },
    { value: "6h", label: t.range6h },
    { value: "24h", label: t.range24h },
    { value: "7d", label: t.range7d },
    { value: "30d", label: t.range30d },
  ];
}

export default function HistoryPanel({ isOpen, onClose }: HistoryPanelProps) {
  const t = useT();
  const [stats, setStats] = useState<ModelStats[]>([]);
  const [timeRange, setTimeRange] = useState<TimeRange>("24h");
  const [loading, setLoading] = useState(false);

  const loadStats = useCallback(async () => {
    setLoading(true);
    try {
      const startTime = getStartTime(timeRange);
      const data = await fetchStats(startTime);
      setStats(data);
    } catch (err) {
      console.error("Failed to fetch stats:", err);
    } finally {
      setLoading(false);
    }
  }, [timeRange]);

  useEffect(() => {
    if (isOpen) {
      loadStats();
    }
  }, [isOpen, loadStats]);

  if (!isOpen) return null;

  const sorted = sortStats(stats);
  const timeRanges = getTimeRanges(t);

  return (
    <div className="fixed inset-0 z-50 flex">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative ml-auto w-full max-w-4xl bg-gray-950 border-l border-gray-800 overflow-y-auto">
        <div className="sticky top-0 bg-gray-950/95 backdrop-blur border-b border-gray-800 px-6 py-4 flex items-center justify-between z-10">
          <h2 className="text-lg font-semibold text-gray-200">
            {t.historyTitle}
          </h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-200 transition-colors"
          >
            <svg
              className="w-5 h-5"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        </div>

        <div className="p-6 space-y-6">
          {/* Time Range Selector */}
          <div className="flex gap-2">
            {timeRanges.map((tr) => (
              <button
                key={tr.value}
                onClick={() => setTimeRange(tr.value)}
                className={`px-3 py-1.5 text-sm rounded-lg transition-colors ${
                  timeRange === tr.value
                    ? "bg-blue-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200"
                }`}
              >
                {tr.label}
              </button>
            ))}
          </div>

          {/* Loading State */}
          {loading && (
            <div className="flex items-center justify-center py-12">
              <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            </div>
          )}

          {/* Stats Cards */}
          {!loading && sorted.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {sorted.map((s) => (
                <div
                  key={s.model_id}
                  className="rounded-xl border border-gray-800 bg-gray-900/50 hover:border-gray-700 transition-colors"
                >
                  {/* Card Header */}
                  <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800/50">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${s.count > 0 ? "bg-emerald-400" : "bg-gray-600"}`} />
                      <h3 className="text-sm font-semibold text-gray-200 truncate">
                        {s.model_name}
                      </h3>
                      {getRegionBadge(s.model_name, t)}
                    </div>
                    <span className="text-xs text-gray-500 tabular-nums shrink-0 ml-2">
                      {s.count}{t.historyProbes}
                    </span>
                  </div>

                  {/* Card Body */}
                  <div className="px-4 py-3 space-y-2.5">
                    {/* TTFT row */}
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500 w-16 shrink-0">TTFT</span>
                      <div className="flex gap-4 text-xs font-mono tabular-nums">
                        <span className="text-gray-500">{t.avg}: <span className={getTtftColor(s.avg_ttft_ms)}>{formatNum(s.avg_ttft_ms)}ms</span></span>
                        <span className="text-gray-500">p50: <span className={getTtftColor(s.p50_ttft_ms)}>{formatNum(s.p50_ttft_ms)}ms</span></span>
                        <span className="text-gray-500">p95: <span className={getTtftColor(s.p95_ttft_ms)}>{formatNum(s.p95_ttft_ms)}ms</span></span>
                      </div>
                    </div>

                    {/* Latency row */}
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500 w-16 shrink-0">Latency</span>
                      <div className="flex gap-4 text-xs font-mono tabular-nums">
                        <span className="text-gray-500">{t.avg}: <span className={getLatencyColor(s.avg_latency_ms)}>{formatNum(s.avg_latency_ms)}ms</span></span>
                        <span className="text-gray-500">p50: <span className={getLatencyColor(s.p50_latency_ms)}>{formatNum(s.p50_latency_ms)}ms</span></span>
                        <span className="text-gray-500">p95: <span className={getLatencyColor(s.p95_latency_ms)}>{formatNum(s.p95_latency_ms)}ms</span></span>
                      </div>
                    </div>

                    {/* TPS row */}
                    <div className="flex items-center justify-between">
                      <span className="text-xs text-gray-500 w-16 shrink-0">TPS</span>
                      <div className="flex gap-4 text-xs font-mono tabular-nums">
                        <span className="text-gray-500">{t.avg}: <span className={getTpsColor(s.avg_tps)}>{formatNum(s.avg_tps, 1)}</span></span>
                        <span className="text-gray-500">p50: <span className={getTpsColor(s.p50_tps)}>{formatNum(s.p50_tps, 1)}</span></span>
                        <span className="text-gray-500">p95: <span className={getTpsColor(s.p95_tps)}>{formatNum(s.p95_tps, 1)}</span></span>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {!loading && stats.length === 0 && (
            <div className="text-center py-12">
              <p className="text-gray-500">
                {t.historyNoData}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
