"use client";

import { memo, useId, useMemo } from "react";
import type { HealthFilter, ModelHealth, MonitoringRow } from "@/lib/monitoring";
import { filterMonitoringRows, summarizeMonitoring } from "@/lib/monitoring";
import { FAMILY_ORDER, familyRank, groupByFamily } from "@/lib/sortModels";
import { useT } from "@/lib/i18n-context";
import ModelName from "./ModelName";

export const HEALTH_STYLES: Record<ModelHealth, string> = {
  healthy: "border-emerald-500/30 bg-emerald-500/10 text-emerald-300",
  error: "border-rose-500/40 bg-rose-500/15 text-rose-300",
  overloaded: "border-amber-500/40 bg-amber-500/15 text-amber-300",
  stale: "border-amber-500/30 bg-amber-500/5 text-amber-300",
  unknown: "border-gray-700 bg-gray-800/50 text-gray-400",
};

export function HealthBadge({ health, id }: { health: ModelHealth; id?: string }) {
  const t = useT();
  return (
    <span
      id={id}
      // 채널 상태(응답 성공·수집 주기) 배지 — 카드 값 색의 "지표 등급"(양호/경고/위험)과 다른 개념임을 툴팁으로 밝힌다.
      title={health === "healthy" ? t.monitoring.healthyHint : undefined}
      className={`inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium ${HEALTH_STYLES[health]}`}
    >
      <span aria-hidden="true">{health === "healthy" ? "✓" : health === "unknown" ? "—" : "!"}</span>
      <span>{t.monitoring.health[health]}</span>
    </span>
  );
}

function MonitoringOverview({ rows, catalogKnown, expectedCount, filter, onFilterChange, selectedModels, onToggleModel, onInspectModel }: {
  rows: MonitoringRow[];
  catalogKnown: boolean;
  expectedCount?: number;
  filter: HealthFilter;
  onFilterChange: (filter: HealthFilter) => void;
  selectedModels: Set<string>;
  onToggleModel: (name: string) => void;
  onInspectModel: (name: string) => void;
}) {
  const t = useT();
  const m = t.monitoring;
  const id = useId();
  const reportedCount = !catalogKnown && typeof expectedCount === "number" && Number.isInteger(expectedCount) && expectedCount >= rows.length ? expectedCount : undefined;
  const coverageKnown = catalogKnown || reportedCount !== undefined;
  const summary = summarizeMonitoring(rows, reportedCount);
  const attentionRows = useMemo(() => filterMonitoringRows(rows, "", "attention", "attention"), [rows]);
  const groups = useMemo(() => groupByFamily(rows.map((row) => ({ ...row, model_name: row.model.name }))), [rows]);
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
            <span className="ui-copy mt-2 block text-xs leading-relaxed text-gray-500">{card.hint}</span>
          </button>
        ))}
        <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
          <p className="text-xs font-medium text-gray-400">{m.successRate}</p>
          <p className="mt-2 text-3xl font-semibold tabular-nums tracking-tight text-gray-100">
            {summary.successRate === null ? "—" : `${(summary.successRate * 100).toFixed(1)}%`}
          </p>
          <p className="ui-copy mt-2 text-xs leading-relaxed text-gray-500">{m.successRateHint}</p>
        </div>
      </div>
      {summary.attention > 0 && (
        <section aria-label={m.attentionChannels} className="rounded-xl border border-amber-500/25 bg-gray-900/50 p-4">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-sm font-semibold text-gray-200">{m.attentionChannels}</h2>
            <p className="ui-copy text-[11px] text-gray-500">{m.latestStateHint}</p>
          </div>
          <div className="grid gap-2 lg:grid-cols-2">
            {attentionRows.slice(0, 6).map((row, index) => (
              <button
                key={row.model.id} type="button" aria-label={m.inspectModel(row.model.name)}
                aria-describedby={`${id}-attention-${index}`}
                onClick={() => onInspectModel(row.model.name)}
                className="flex min-h-12 min-w-0 items-center gap-3 rounded-lg border border-gray-800 bg-gray-950/50 px-3 py-2 text-left hover:border-blue-500/50 hover:bg-gray-800/30"
              >
                <span className="min-w-0 flex-1 text-xs font-medium leading-relaxed text-gray-200"><ModelName name={row.model.name} /></span>
                <HealthBadge health={row.health} id={`${id}-attention-${index}`} />
                <span aria-hidden="true" className="text-gray-500">→</span>
              </button>
            ))}
          </div>
          {summary.unlisted > 0 && <p className="ui-copy mt-3 text-xs text-amber-300">{m.unlistedChannels(summary.unlisted)}</p>}
          <button type="button" className="mt-3 min-h-9 rounded-md text-xs font-medium text-blue-300 hover:underline"
            onClick={() => onFilterChange("attention")}>{m.viewAllAttention} <span aria-hidden="true">→</span></button>
        </section>
      )}
      {rows.length > 0 && (
        <details className="group rounded-xl border border-gray-800 bg-gray-900/50 px-4 py-3">
          <summary className="flex min-h-6 cursor-pointer list-none items-center justify-between gap-3 text-xs [&::-webkit-details-marker]:hidden">
            <span className="font-medium text-gray-300">{m.allChannelStates} <span className="ml-2 font-normal text-gray-500">{m.channelCount(rows.length)}</span></span>
            <span aria-hidden="true" className="text-gray-500 transition-transform group-open:rotate-180">⌄</span>
          </summary>
          <div className="mt-4 max-h-80 space-y-4 overflow-auto p-1">
            {groups.map((group) => {
              const family = FAMILY_ORDER[familyRank(group[0].model.name)];
              return (
                <div key={family ?? "other"} className="space-y-2">
                  <p className="text-xs font-semibold text-gray-300">{family ?? m.otherModels}</p>
                  <div className="flex flex-wrap gap-2">
                    {group.map((row) => (
                      <button
                        key={row.model.id} type="button"
                        onClick={() => onToggleModel(row.model.name)}
                        aria-label={`${m.selectModel(row.model.name)}: ${m.health[row.health]}`}
                        aria-pressed={selectedModels.has(row.model.name)}
                        title={`${row.model.name} · ${m.health[row.health]}`}
                        className={`inline-flex min-h-9 items-center gap-2 rounded-md border px-2.5 py-1 text-xs font-medium ${HEALTH_STYLES[row.health]} ${selectedModels.has(row.model.name) ? "ring-2 ring-blue-400 ring-offset-2 ring-offset-gray-950" : ""}`}
                      >
                        <span aria-hidden="true">{row.health === "healthy" ? "✓" : row.health === "unknown" ? "—" : "!"}</span>
                        <ModelName name={family ? row.model.name.replace(family, "").trim() : row.model.name} />
                      </button>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="ui-copy mt-3 text-xs text-gray-500">{m.selectHint}</p>
        </details>
      )}
    </section>
  );
}

export default memo(MonitoringOverview);
