"use client";

import { ProbeResult } from "@/lib/types";
import { useMemo } from "react";

interface StatsCardsProps {
  results: ProbeResult[];
}

interface ComputedStats {
  avgTTFT: number | null;
  p50TTFT: number | null;
  p95TTFT: number | null;
  avgTPS: number | null;
  avgLatency: number | null;
  errorRate: number;
  totalProbes: number;
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const idx = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(idx);
  const upper = Math.ceil(idx);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (idx - lower);
}

function computeStats(results: ProbeResult[]): ComputedStats {
  const ttftValues = results
    .map((r) => r.ttft_ms)
    .filter((v): v is number => v !== null && v !== undefined)
    .sort((a, b) => a - b);

  const tpsValues = results
    .map((r) => r.tps)
    .filter((v): v is number => v !== null && v !== undefined);

  const latencyValues = results
    .map((r) => r.total_latency_ms)
    .filter((v): v is number => v !== null && v !== undefined);

  const errors = results.filter((r) => r.status !== "success").length;

  return {
    avgTTFT:
      ttftValues.length > 0
        ? ttftValues.reduce((s, v) => s + v, 0) / ttftValues.length
        : null,
    p50TTFT: ttftValues.length > 0 ? percentile(ttftValues, 50) : null,
    p95TTFT: ttftValues.length > 0 ? percentile(ttftValues, 95) : null,
    avgTPS:
      tpsValues.length > 0
        ? tpsValues.reduce((s, v) => s + v, 0) / tpsValues.length
        : null,
    avgLatency:
      latencyValues.length > 0
        ? latencyValues.reduce((s, v) => s + v, 0) / latencyValues.length
        : null,
    errorRate: results.length > 0 ? (errors / results.length) * 100 : 0,
    totalProbes: results.length,
  };
}

function StatCard({
  label,
  value,
  unit,
  subtext,
  colorClass,
}: {
  label: string;
  value: string;
  unit?: string;
  subtext?: string;
  colorClass: string;
}) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
        {label}
      </p>
      <div className="flex items-baseline gap-1">
        <span className={`text-2xl font-bold tabular-nums ${colorClass}`}>
          {value}
        </span>
        {unit && <span className="text-sm text-gray-500">{unit}</span>}
      </div>
      {subtext && (
        <p className="text-xs text-gray-500 mt-1 tabular-nums">{subtext}</p>
      )}
    </div>
  );
}

export default function StatsCards({ results }: StatsCardsProps) {
  const stats = useMemo(() => computeStats(results), [results]);

  if (results.length === 0) return null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
      <StatCard
        label="Avg TTFT"
        value={stats.avgTTFT !== null ? stats.avgTTFT.toFixed(0) : "-"}
        unit="ms"
        subtext={
          stats.p50TTFT !== null
            ? `p50: ${stats.p50TTFT.toFixed(0)}ms / p95: ${stats.p95TTFT?.toFixed(0)}ms`
            : undefined
        }
        colorClass={
          stats.avgTTFT !== null && stats.avgTTFT < 300
            ? "text-emerald-400"
            : stats.avgTTFT !== null && stats.avgTTFT < 800
            ? "text-amber-400"
            : "text-rose-400"
        }
      />
      <StatCard
        label="Avg TPS"
        value={stats.avgTPS !== null ? stats.avgTPS.toFixed(1) : "-"}
        unit="tok/s"
        colorClass={
          stats.avgTPS !== null && stats.avgTPS > 80
            ? "text-emerald-400"
            : stats.avgTPS !== null && stats.avgTPS > 40
            ? "text-amber-400"
            : "text-rose-400"
        }
      />
      <StatCard
        label="Avg Latency"
        value={stats.avgLatency !== null ? stats.avgLatency.toFixed(0) : "-"}
        unit="ms"
        colorClass={
          stats.avgLatency !== null && stats.avgLatency < 3000
            ? "text-emerald-400"
            : stats.avgLatency !== null && stats.avgLatency < 8000
            ? "text-amber-400"
            : "text-rose-400"
        }
      />
      <StatCard
        label="Error Rate"
        value={stats.errorRate.toFixed(1)}
        unit="%"
        colorClass={
          stats.errorRate === 0
            ? "text-emerald-400"
            : stats.errorRate < 10
            ? "text-amber-400"
            : "text-rose-400"
        }
      />
      <StatCard
        label="Total Probes"
        value={String(stats.totalProbes)}
        colorClass="text-blue-400"
      />
    </div>
  );
}
