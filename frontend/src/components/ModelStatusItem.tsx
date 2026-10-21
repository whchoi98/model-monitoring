"use client";

import { memo, useId } from "react";
import { useLang, useT } from "@/lib/i18n-context";
import type { MetricGradeTexts } from "@/lib/i18n";
import type { MonitoringRow } from "@/lib/monitoring";
import { formatAge, formatDateTime } from "@/lib/format";
import {
  GRADE_MARKER, GRADE_TEXT_CLASS, describeGrade, formatMetricValue, roundForDisplay, type GradeRule,
} from "@/lib/metricGrade";
import { HealthBadge } from "./MonitoringOverview";
import ModelName from "./ModelName";

export type ModelLayout = "compact" | "cards";

function gradeHint(g: MetricGradeTexts, rule: GradeRule, metric: string): string | undefined {
  if (rule.grade === "none") return undefined;
  const scope = rule.lowerIsWorse ? g.allWorkloads : rule.category ? g.categories[rule.category] : g.defaultCategory;
  return g.hint({ grade: rule.grade, metric, scope, warnAt: rule.warnAt, critAt: rule.critAt, unit: rule.unit, lowerIsWorse: rule.lowerIsWorse });
}

/** Both layouts use the same measurements, freshness, grading and selection contract. */
function ModelStatusItem({ row, selected, onToggleModel, now, layout }: {
  row: MonitoringRow;
  selected: boolean;
  onToggleModel: (name: string) => void;
  now: number;
  layout: ModelLayout;
}) {
  const t = useT();
  const { lang } = useLang();
  const m = t.monitoring;
  const id = useId();
  const { model, result, health, freshness } = row;
  const compact = layout === "compact";
  const success = result?.status === "success";
  const metrics = success && result ? ([
    { key: "ttft", name: "TTFT", raw: result.ttft_ms, unit: "ms" },
    { key: "total", name: t.metrics.totalLatency.name, raw: result.total_latency_ms, unit: "s" },
    { key: "tps", name: "TPS", raw: result.tps, unit: "tok/s" },
  ] as const).map((metric) => {
    const shown = roundForDisplay(metric.key, metric.raw);
    const rule = describeGrade(metric.key, shown, result.category);
    return { ...metric, value: formatMetricValue(metric.key, shown), rule, hint: gradeHint(m.grade, rule, metric.name) };
  }) : [];
  const issues = metrics.filter((metric) => metric.rule.grade === "warning" || metric.rule.grade === "critical");
  const issuesId = issues.length ? `${id}-grade` : undefined;
  const time = result?.timestamp ? formatAge(result.timestamp, lang, now) : "—";

  return (
    <article
      data-layout={layout}
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
        aria-describedby={issuesId}
        onClick={() => onToggleModel(model.name)}
        className={`w-full rounded-xl text-left hover:bg-gray-800/25 ${
          compact ? "grid grid-cols-1 gap-2 px-3 py-2.5 sm:px-4 md:grid-cols-[minmax(0,1fr)_21rem] md:items-center md:gap-6"
            : "block p-4"
        }`}
      >
        <span className={`flex items-start justify-between gap-2 ${compact ? "md:items-center" : "mb-3"}`}>
          <span className={`min-w-0 ${compact ? "md:flex md:flex-wrap md:items-baseline md:gap-x-3" : ""}`}>
            <span className="block text-sm font-semibold leading-snug text-gray-200">
              {selected && <span aria-hidden="true" className="mr-1.5 text-blue-400">✓</span>}
              <ModelName name={model.name} />
            </span>
            {compact ? (
              <span className="mt-1 block text-[11px] text-gray-500 md:mt-0 md:whitespace-nowrap" title={formatDateTime(result?.timestamp, lang)}>
                <span className="md:sr-only">{m.lastResult} · </span>{time}
              </span>
            ) : (
              <code className="mt-1 block truncate text-[11px] text-gray-500" title={model.id}>{model.id}</code>
            )}
          </span>
          <HealthBadge health={health} />
        </span>
        {success && result ? (
          <span className="grid grid-cols-3 gap-2">
            {metrics.map((metric) => (
              <span key={metric.key} className="min-w-0">
                <span className={`block text-[11px] text-gray-500 ${compact ? "md:sr-only" : ""}`}>{metric.name}</span>
                <span data-grade={metric.rule.grade} title={metric.hint}
                  className={`flex min-w-0 flex-wrap items-baseline gap-x-1 font-mono text-base font-medium tabular-nums ${compact ? "mt-0.5 md:mt-0" : "mt-1"} ${GRADE_TEXT_CLASS[metric.rule.grade]}`}>
                  <span>{metric.value}</span>
                  {metric.value !== "—" && <span className="text-[11px] font-normal text-gray-500">{metric.unit}</span>}
                  {GRADE_MARKER[metric.rule.grade] && (
                    <span aria-hidden="true" data-marker={metric.rule.grade} className="text-xs">{GRADE_MARKER[metric.rule.grade]}</span>
                  )}
                </span>
              </span>
            ))}
          </span>
        ) : (
          <span className={`line-clamp-2 break-words text-xs leading-relaxed ${result?.status === "overloaded" ? "text-amber-300" : result ? "text-rose-300" : "text-gray-400"}`}>
            {result?.status === "overloaded" ? t.overloadedHint : result?.error_message || m.missingHint}
          </span>
        )}
        {!compact && success && result && (
          <span className="mt-3 block text-[11px] text-gray-500">
            {t.metrics.inputTokens.name}: {result.input_tokens ?? "—"} · {t.metrics.outputTokens.name}: {result.output_tokens ?? "—"}
          </span>
        )}
        {!compact && (
          <span className="mt-3 flex flex-wrap items-center justify-between gap-1 border-t border-gray-800 pt-2 text-[11px] text-gray-500">
            <span>{selected ? `✓ ${m.selection(1)}` : m.lastResult}</span>
            <span title={formatDateTime(result?.timestamp, lang)}>{time}</span>
          </span>
        )}
        {(freshness === "stale" || (result && freshness === "unknown")) && (
          <span className={`ui-copy block text-xs leading-relaxed text-amber-300 ${compact ? "md:col-span-2" : "mt-2"}`}>
            {freshness === "stale" ? m.staleHint : m.unknownTime}
          </span>
        )}
        {issuesId && (
          <span id={issuesId} className="sr-only">
            {issues.map((metric) => `${metric.name} ${metric.value} ${metric.unit}, ${metric.hint}`).join(". ")}
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
}

export default memo(ModelStatusItem);
