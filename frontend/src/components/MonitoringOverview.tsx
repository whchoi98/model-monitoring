"use client";

import type { HealthFilter, ModelHealth, MonitoringRow } from "@/lib/monitoring";
import { summarizeMonitoring } from "@/lib/monitoring";
import { useT } from "@/lib/i18n-context";

export const HEALTH_STYLES: Record<ModelHealth, string> = {
  healthy: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  error: "border-rose-500/40 bg-rose-500/15 text-rose-300",
  overloaded: "border-amber-500/40 bg-amber-500/15 text-amber-300",
  stale: "border-amber-500/30 bg-amber-500/5 text-amber-300",
  unknown: "border-gray-700 bg-gray-800/50 text-gray-400",
};

export function HealthBadge({ health }: { health: ModelHealth }) {
  const t = useT();
  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${HEALTH_STYLES[health]}`}>
      <span aria-hidden="true">{health === "healthy" ? "✓" : health === "unknown" ? "—" : "!"}</span>
      <span>{t.monitoring.health[health]}</span>
    </span>
  );
}

export default function MonitoringOverview({ rows, catalogKnown, expectedCount, filter, onFilterChange, selectedModels, onToggleModel }: {
  rows: MonitoringRow[];
  catalogKnown: boolean;
  expectedCount?: number;
  filter: HealthFilter;
  onFilterChange: (filter: HealthFilter) => void;
  selectedModels: Set<string>;
  onToggleModel: (name: string) => void;
}) {
  const t = useT();
  const m = t.monitoring;
  const reportedCount = !catalogKnown && typeof expectedCount === "number" && Number.isInteger(expectedCount) && expectedCount >= rows.length ? expectedCount : undefined;
  const coverageKnown = catalogKnown || reportedCount !== undefined;
  const summary = summarizeMonitoring(rows, reportedCount);
  const cards = [
    { label: m.monitored, value: coverageKnown ? summary.total : "—", hint: m.observed(summary.observed), color: "text-gray-100", filter: "all" as const },
    { label: m.healthy, value: summary.healthy, hint: m.healthyHint, color: "text-emerald-400", filter: "healthy" as const },
    { label: m.attention, value: coverageKnown ? summary.attention : summary.attention ? `${summary.attention}+` : "—", hint: coverageKnown ? m.attentionHint : m.catalogRequired, color: summary.attention ? "text-amber-400" : "text-gray-100", filter: "attention" as const },
  ];
  return (
    <section aria-label={m.overview} className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {cards.map((card) => (
          <button
            key={card.filter}
            type="button"
            aria-pressed={filter === card.filter}
            aria-label={`${card.label} ${card.value}`}
            onClick={() => onFilterChange(card.filter)}
            className={`rounded-xl border bg-gray-900/50 p-4 text-left transition-colors hover:border-blue-400 ${filter === card.filter ? "border-blue-500/60" : "border-gray-800"}`}
          >
            <span className="text-xs font-medium text-gray-400">{card.label}</span>
            <span className={`mt-2 block text-3xl font-semibold tabular-nums tracking-tight ${card.color}`}>{card.value}</span>
            <span className="mt-2 block text-xs leading-relaxed text-gray-500">{card.hint}</span>
          </button>
        ))}
        <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
          <p className="text-xs font-medium text-gray-400">{m.successRate}</p>
          <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-gray-100">
            {summary.successRate === null ? "—" : `${(summary.successRate * 100).toFixed(1)}%`}
          </p>
          <p className="mt-2 text-xs leading-relaxed text-gray-500">{m.successRateHint}</p>
        </div>
      </div>
      {rows.length > 0 && (
        <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-medium text-gray-300">{t.modelStatus}</p>
            <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-400">
              {(Object.keys(HEALTH_STYLES) as ModelHealth[]).map((health) => (
                <span key={health} className="inline-flex items-center gap-1.5">
                  <span aria-hidden="true" className={`h-2.5 w-2.5 rounded-sm border ${HEALTH_STYLES[health]}`} />
                  {m.health[health]}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {rows.map((row) => (
              <button
                key={row.model.id}
                type="button"
                onClick={() => onToggleModel(row.model.name)}
                aria-label={`${m.selectModel(row.model.name)}: ${m.health[row.health]}`}
                aria-pressed={selectedModels.has(row.model.name)}
                title={`${row.model.name} · ${m.health[row.health]}`}
                className={`flex h-7 w-7 items-center justify-center rounded-md border text-xs font-medium ${HEALTH_STYLES[row.health]} ${selectedModels.has(row.model.name) ? "ring-2 ring-blue-400 ring-offset-2 ring-offset-gray-950" : ""}`}
              >
                {row.health === "healthy" ? "✓" : row.health === "unknown" ? "—" : "!"}
              </button>
            ))}
          </div>
          {summary.unlisted > 0 && <p className="mt-3 text-xs text-amber-300">{m.unlistedChannels(summary.unlisted)}</p>}
        </div>
      )}
    </section>
  );
}
