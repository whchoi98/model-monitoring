"use client";

import { ProbeResult } from "@/lib/types";
import { Translations } from "@/lib/i18n";
import { useT } from "@/lib/i18n-context";
import { useState } from "react";

interface Props {
  results: ProbeResult[];
}

function MetricTooltip({ text }: { text: string }) {
  const [show, setShow] = useState(false);
  return (
    <span
      className="relative inline-flex items-center"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      <svg className="w-3.5 h-3.5 text-gray-500 hover:text-gray-300 cursor-help ml-1" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      {show && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-2 bg-gray-800 border border-gray-700 rounded-lg shadow-xl text-xs text-gray-300 leading-relaxed">
          {text}
          <div className="absolute top-full left-1/2 -translate-x-1/2 -mt-px border-4 border-transparent border-t-gray-800" />
        </div>
      )}
    </span>
  );
}

function getLatencyColor(ms: number | null): string {
  if (ms === null) return "text-gray-500";
  if (ms < 2000) return "text-emerald-400";
  if (ms < 5000) return "text-amber-400";
  return "text-rose-400";
}

function getTtftColor(ms: number | null): string {
  if (ms === null) return "text-gray-500";
  if (ms < 1000) return "text-emerald-400";
  if (ms < 3000) return "text-amber-400";
  return "text-rose-400";
}

function getTpsColor(tps: number | null): string {
  if (tps === null) return "text-gray-500";
  if (tps > 50) return "text-emerald-400";
  if (tps > 20) return "text-amber-400";
  return "text-rose-400";
}

function getStatusBadge(status: string, t: Translations) {
  if (status === "success") {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
        {t.success}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-rose-500/10 text-rose-400 border border-rose-500/20">
      <span className="w-1.5 h-1.5 rounded-full bg-rose-400" />
      {t.error}
    </span>
  );
}

function formatTime(timestamp: string | undefined, t: Translations): string {
  if (!timestamp) return "-";
  const d = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return t.justNow;
  if (diffMin < 60) return t.minutesAgo(diffMin);
  return t.hoursAgo(Math.floor(diffMin / 60));
}

/** Extract a sort key from model_name: [regionOrder, -version, tierOrder]. */
function modelSortKey(name: string): [number, number, number] {
  // Region: Global first (0), US second (1), others last (2)
  const regionOrder = name.includes("(Global)") ? 0 : name.includes("(US)") ? 1 : 2;

  // Version: extract major.minor (e.g. "4.7" → 4.7), higher = first (negate for ascending sort)
  const verMatch = name.match(/(\d+\.\d+)/);
  const version = verMatch ? parseFloat(verMatch[1]) : 0;

  // Tier: Opus (0) > Sonnet (1) > Haiku (2) > others (3)
  const tierOrder = name.includes("Opus") ? 0 : name.includes("Sonnet") ? 1 : name.includes("Haiku") ? 2 : 3;

  return [regionOrder, -version, tierOrder];
}

function compareModels(a: ProbeResult, b: ProbeResult): number {
  const ka = modelSortKey(a.model_name);
  const kb = modelSortKey(b.model_name);
  for (let i = 0; i < ka.length; i++) {
    if (ka[i] !== kb[i]) return ka[i] - kb[i];
  }
  return 0;
}

export default function ModelStatusGrid({ results }: Props) {
  const t = useT();

  if (results.length === 0) return null;

  const sorted = [...results].sort(compareModels);

  return (
    <div>
      <h2 className="text-lg font-semibold text-gray-100 mb-4">{t.modelStatus}</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {sorted.map((r) => (
          <div
            key={r.model_id}
            className={`rounded-xl border p-4 transition-colors ${
              r.status === "success"
                ? "bg-gray-900/50 border-gray-800 hover:border-gray-700"
                : "bg-rose-950/20 border-rose-900/30 hover:border-rose-800/40"
            }`}
          >
            {/* Header */}
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-gray-200 truncate pr-2">
                {r.model_name}
              </h3>
              {getStatusBadge(r.status, t)}
            </div>

            {r.status === "success" ? (
              <div className="space-y-2">
                {/* TTFT */}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 flex items-center">
                    {t.metrics.ttft.name}
                    <MetricTooltip text={t.metrics.ttft.desc} />
                  </span>
                  <span className={`text-sm font-mono font-medium ${getTtftColor(r.ttft_ms)}`}>
                    {r.ttft_ms !== null ? `${r.ttft_ms.toFixed(0)} ms` : "-"}
                  </span>
                </div>

                {/* Total Latency */}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 flex items-center">
                    {t.metrics.totalLatency.name}
                    <MetricTooltip text={t.metrics.totalLatency.desc} />
                  </span>
                  <span className={`text-sm font-mono font-medium ${getLatencyColor(r.total_latency_ms)}`}>
                    {r.total_latency_ms !== null ? `${(r.total_latency_ms / 1000).toFixed(1)}s` : "-"}
                  </span>
                </div>

                {/* TPS */}
                <div className="flex items-center justify-between">
                  <span className="text-xs text-gray-500 flex items-center">
                    {t.metrics.tps.name}
                    <MetricTooltip text={t.metrics.tps.desc} />
                  </span>
                  <span className={`text-sm font-mono font-medium ${getTpsColor(r.tps)}`}>
                    {r.tps !== null ? `${r.tps.toFixed(1)} tok/s` : "-"}
                  </span>
                </div>

                {/* Tokens */}
                <div className="flex items-center justify-between pt-1 border-t border-gray-800/50">
                  <span className="text-xs text-gray-600">
                    {t.metrics.inputTokens.name}: {r.input_tokens ?? "-"} / {t.metrics.outputTokens.name}: {r.output_tokens ?? "-"}
                  </span>
                </div>
              </div>
            ) : (
              <div className="text-xs text-rose-400/80 truncate">
                {r.error_message || "Unknown error"}
              </div>
            )}

            {/* Timestamp */}
            <div className="mt-2 text-xs text-gray-600 text-right">
              {formatTime(r.timestamp, t)}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
