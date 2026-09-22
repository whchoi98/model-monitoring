"use client";

import { useLang, useT } from "@/lib/i18n-context";
import type { MonitoringRow } from "@/lib/monitoring";
import { formatAge, formatDateTime } from "@/lib/format";
import { groupByFamily } from "@/lib/sortModels";
import { HealthBadge } from "./MonitoringOverview";

interface Props {
  rows: MonitoringRow[];
  onToggleModel: (name: string) => void;
  selectedModels: Set<string>;
  now: number;
  grouped?: boolean;
}

export default function ModelStatusGrid({ rows, onToggleModel, selectedModels, now, grouped = true }: Props) {
  const t = useT();
  const { lang } = useLang();
  const m = t.monitoring;
  const groups = grouped ? groupByFamily(rows.map((row) => ({ ...row, model_name: row.model.name }))) : [rows];

  return (
    <div className="space-y-4">
      {groups.map((group) => (
      <div key={group[0]?.model.id ?? "models"} className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {group.map(({ model, result, health, freshness }) => {
        const selected = selectedModels.has(model.name);
        const success = result?.status === "success";
        return (
          <article
            key={model.id}
            className={`min-w-0 rounded-xl border bg-gray-900/50 transition-colors ${
              selected ? "border-blue-500 ring-1 ring-blue-500/40"
                : health === "error" ? "border-rose-500/35"
                  : health === "overloaded" || health === "stale" ? "border-amber-500/30" : "border-gray-800"
            }`}
          >
            <button
              type="button"
              aria-label={m.selectModel(model.name)}
              aria-pressed={selected}
              onClick={() => onToggleModel(model.name)}
              className="block w-full rounded-xl p-4 text-left hover:bg-gray-800/25"
            >
              <span className="mb-3 flex items-start justify-between gap-2">
                <span className="min-w-0">
                  <span className="block text-sm font-semibold leading-snug text-gray-200">{model.name}</span>
                  <code className="mt-1 block truncate text-[11px] text-gray-500" title={model.id}>{model.id}</code>
                </span>
                <HealthBadge health={health} />
              </span>
              {success && result ? (
                <span className="grid grid-cols-3 gap-2">
                  {[
                    { name: "TTFT", value: result.ttft_ms == null ? "—" : `${Math.round(result.ttft_ms)}`, unit: "ms" },
                    { name: t.metrics.totalLatency.name, value: result.total_latency_ms == null ? "—" : (result.total_latency_ms / 1000).toFixed(1), unit: "s" },
                    { name: "TPS", value: result.tps == null ? "—" : result.tps.toFixed(1), unit: "tok/s" },
                  ].map((metric) => (
                    <span key={metric.name}>
                      <span className="block text-[11px] text-gray-500">{metric.name}</span>
                      <span className="mt-1 block font-mono text-base font-medium tabular-nums text-gray-200">
                        {metric.value}<span className="ml-1 text-[11px] font-normal text-gray-500">{metric.value !== "—" ? metric.unit : ""}</span>
                      </span>
                    </span>
                  ))}
                </span>
              ) : (
                <span className={`line-clamp-2 break-words text-xs leading-relaxed ${result?.status === "overloaded" ? "text-amber-300" : result ? "text-rose-300" : "text-gray-400"}`}>
                  {result?.status === "overloaded" ? t.overloadedHint : result?.error_message || m.missingHint}
                </span>
              )}
              {success && result && (
                <span className="mt-3 block text-[11px] text-gray-500">
                  {t.metrics.inputTokens.name}: {result.input_tokens ?? "—"} · {t.metrics.outputTokens.name}: {result.output_tokens ?? "—"}
                </span>
              )}
              <span className="mt-3 flex flex-wrap items-center justify-between gap-1 border-t border-gray-800 pt-2 text-[11px] text-gray-500">
                <span>{selected ? `✓ ${m.selection(1)}` : m.lastResult}</span>
                <span title={formatDateTime(result?.timestamp, lang)}>
                  {result?.timestamp ? formatAge(result.timestamp, lang, now) : "—"}
                </span>
              </span>
              {(freshness === "stale" || (result && freshness === "unknown")) && (
                <span className="mt-2 block text-xs leading-relaxed text-amber-300">
                  {freshness === "stale" ? m.staleHint : m.unknownTime}
                </span>
              )}
            </button>
            {result?.error_message && (
              <details className="mx-4 mb-3 border-t border-gray-800 pt-2">
                <summary className="cursor-pointer text-xs text-gray-400">{m.showDetails}</summary>
                <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-gray-950 p-3 text-xs leading-relaxed text-rose-300">
                  {result.error_message}
                </pre>
              </details>
            )}
          </article>
        );
      })}
      </div>
      ))}
    </div>
  );
}
