"use client";

import { useMemo } from "react";
import { ProbeResult } from "@/lib/types";

interface ComparisonViewProps {
  results: ProbeResult[];
}

interface ModelDistribution {
  model_name: string;
  ttft: { min: number; p50: number; p95: number; p99: number; max: number } | null;
  latency: { min: number; p50: number; p95: number; p99: number; max: number } | null;
  tps: { min: number; p50: number; p95: number; p99: number; max: number } | null;
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const idx = (p / 100) * (sorted.length - 1);
  const lower = Math.floor(idx);
  const upper = Math.ceil(idx);
  if (lower === upper) return sorted[lower];
  return sorted[lower] + (sorted[upper] - sorted[lower]) * (idx - lower);
}

function computeDistribution(
  values: number[]
): { min: number; p50: number; p95: number; p99: number; max: number } | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return {
    min: sorted[0],
    p50: percentile(sorted, 50),
    p95: percentile(sorted, 95),
    p99: percentile(sorted, 99),
    max: sorted[sorted.length - 1],
  };
}

function computeModelDistributions(
  results: ProbeResult[]
): ModelDistribution[] {
  const byModel = new Map<
    string,
    { ttfts: number[]; latencies: number[]; tps: number[] }
  >();

  for (const r of results) {
    if (r.status !== "success") continue;
    if (!byModel.has(r.model_name)) {
      byModel.set(r.model_name, { ttfts: [], latencies: [], tps: [] });
    }
    const entry = byModel.get(r.model_name)!;
    if (r.ttft_ms !== null) entry.ttfts.push(r.ttft_ms);
    if (r.total_latency_ms !== null) entry.latencies.push(r.total_latency_ms);
    if (r.tps !== null) entry.tps.push(r.tps);
  }

  const distributions: ModelDistribution[] = [];
  byModel.forEach((vals, model_name) => {
    distributions.push({
      model_name,
      ttft: computeDistribution(vals.ttfts),
      latency: computeDistribution(vals.latencies),
      tps: computeDistribution(vals.tps),
    });
  });

  return distributions.sort((a, b) => a.model_name.localeCompare(b.model_name));
}

function DistributionBar({
  dist,
  globalMax,
  colorClass,
  unit,
}: {
  dist: { min: number; p50: number; p95: number; p99: number; max: number };
  globalMax: number;
  colorClass: string;
  unit: string;
}) {
  if (globalMax === 0) return <div className="text-xs text-gray-600">-</div>;

  const scale = (val: number) => (val / globalMax) * 100;

  const minPos = scale(dist.min);
  const p50Pos = scale(dist.p50);
  const p95Pos = scale(dist.p95);
  const maxPos = scale(dist.max);

  return (
    <div className="space-y-1">
      <div className="relative h-6 bg-gray-800 rounded">
        {/* Range bar from min to max */}
        <div
          className="absolute h-full bg-gray-700 rounded"
          style={{
            left: `${minPos}%`,
            width: `${Math.max(maxPos - minPos, 0.5)}%`,
          }}
        />
        {/* P50 to P95 bar */}
        <div
          className={`absolute h-full ${colorClass} rounded opacity-60`}
          style={{
            left: `${p50Pos}%`,
            width: `${Math.max(scale(dist.p95) - p50Pos, 0.5)}%`,
          }}
        />
        {/* P50 marker */}
        <div
          className={`absolute top-0 h-full w-0.5 ${colorClass}`}
          style={{ left: `${p50Pos}%` }}
        />
      </div>
      <div className="flex justify-between text-[10px] text-gray-500 tabular-nums font-mono">
        <span>min: {dist.min.toFixed(0)}{unit}</span>
        <span className="text-gray-300">p50: {dist.p50.toFixed(0)}{unit}</span>
        <span>p95: {dist.p95.toFixed(0)}{unit}</span>
        <span>p99: {dist.p99.toFixed(0)}{unit}</span>
        <span>max: {dist.max.toFixed(0)}{unit}</span>
      </div>
    </div>
  );
}

export default function ComparisonView({ results }: ComparisonViewProps) {
  const distributions = useMemo(
    () => computeModelDistributions(results),
    [results]
  );

  if (distributions.length === 0) return null;

  // Compute global maximums for scaling
  const globalTTFTMax = Math.max(
    ...distributions
      .filter((d) => d.ttft)
      .map((d) => d.ttft!.max),
    1
  );
  const globalLatencyMax = Math.max(
    ...distributions
      .filter((d) => d.latency)
      .map((d) => d.latency!.max),
    1
  );
  const globalTPSMax = Math.max(
    ...distributions
      .filter((d) => d.tps)
      .map((d) => d.tps!.max),
    1
  );

  return (
    <div className="space-y-3">
      <h2 className="text-lg font-semibold text-gray-200">
        Model Comparison
      </h2>
      <div className="space-y-4">
        {distributions.map((dist) => (
          <div
            key={dist.model_name}
            className="bg-gray-900 border border-gray-800 rounded-xl p-4"
          >
            <h3 className="text-sm font-semibold text-gray-200 mb-3">
              {dist.model_name}
            </h3>
            <div className="space-y-3">
              {/* TTFT Distribution */}
              {dist.ttft && (
                <div>
                  <p className="text-xs text-gray-400 mb-1">
                    TTFT (ms)
                  </p>
                  <DistributionBar
                    dist={dist.ttft}
                    globalMax={globalTTFTMax}
                    colorClass="bg-blue-500"
                    unit="ms"
                  />
                </div>
              )}
              {/* Latency Distribution */}
              {dist.latency && (
                <div>
                  <p className="text-xs text-gray-400 mb-1">
                    Total Latency (ms)
                  </p>
                  <DistributionBar
                    dist={dist.latency}
                    globalMax={globalLatencyMax}
                    colorClass="bg-amber-500"
                    unit="ms"
                  />
                </div>
              )}
              {/* TPS Distribution */}
              {dist.tps && (
                <div>
                  <p className="text-xs text-gray-400 mb-1">
                    TPS (tokens/sec)
                  </p>
                  <DistributionBar
                    dist={dist.tps}
                    globalMax={globalTPSMax}
                    colorClass="bg-emerald-500"
                    unit=""
                  />
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
