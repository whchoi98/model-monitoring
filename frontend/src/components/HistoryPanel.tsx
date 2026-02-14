"use client";

import { useState, useEffect, useCallback } from "react";
import { ModelStats } from "@/lib/types";
import { fetchStats } from "@/lib/api";

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

export default function HistoryPanel({ isOpen, onClose }: HistoryPanelProps) {
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

  const timeRanges: { value: TimeRange; label: string }[] = [
    { value: "1h", label: "1 Hour" },
    { value: "6h", label: "6 Hours" },
    { value: "24h", label: "24 Hours" },
    { value: "7d", label: "7 Days" },
    { value: "30d", label: "30 Days" },
  ];

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
            Historical Stats
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

          {/* Stats Table */}
          {!loading && stats.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-800">
                      <th className="px-3 py-2.5 text-left text-xs font-semibold text-gray-400 uppercase">
                        Model
                      </th>
                      <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase">
                        Count
                      </th>
                      <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase">
                        TTFT Avg
                      </th>
                      <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase">
                        TTFT p50
                      </th>
                      <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase">
                        TTFT p95
                      </th>
                      <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase">
                        Lat Avg
                      </th>
                      <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase">
                        Lat p95
                      </th>
                      <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase">
                        TPS Avg
                      </th>
                      <th className="px-3 py-2.5 text-right text-xs font-semibold text-gray-400 uppercase">
                        TPS p50
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-800/50">
                    {stats.map((s) => (
                      <tr
                        key={s.model_id}
                        className="hover:bg-gray-800/30 transition-colors"
                      >
                        <td className="px-3 py-2 text-gray-200 font-medium whitespace-nowrap">
                          {s.model_name}
                        </td>
                        <td className="px-3 py-2 text-gray-400 text-right tabular-nums">
                          {s.count}
                        </td>
                        <td className="px-3 py-2 text-gray-300 text-right tabular-nums font-mono">
                          {formatNum(s.avg_ttft_ms)}ms
                        </td>
                        <td className="px-3 py-2 text-gray-300 text-right tabular-nums font-mono">
                          {formatNum(s.p50_ttft_ms)}ms
                        </td>
                        <td className="px-3 py-2 text-gray-300 text-right tabular-nums font-mono">
                          {formatNum(s.p95_ttft_ms)}ms
                        </td>
                        <td className="px-3 py-2 text-gray-300 text-right tabular-nums font-mono">
                          {formatNum(s.avg_latency_ms)}ms
                        </td>
                        <td className="px-3 py-2 text-gray-300 text-right tabular-nums font-mono">
                          {formatNum(s.p95_latency_ms)}ms
                        </td>
                        <td className="px-3 py-2 text-gray-300 text-right tabular-nums font-mono">
                          {formatNum(s.avg_tps, 1)}
                        </td>
                        <td className="px-3 py-2 text-gray-300 text-right tabular-nums font-mono">
                          {formatNum(s.p50_tps, 1)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {!loading && stats.length === 0 && (
            <div className="text-center py-12">
              <p className="text-gray-500">
                No historical data available for this time range.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
