"use client";

import { useId } from "react";
import { useLang, useT } from "@/lib/i18n-context";
import type { MetricGradeTexts } from "@/lib/i18n";
import type { MonitoringRow } from "@/lib/monitoring";
import { formatAge, formatDateTime } from "@/lib/format";
import { groupByFamily } from "@/lib/sortModels";
import {
  FALLBACK_LATENCY_THRESHOLDS, GRADE_MARKER, GRADE_TEXT_CLASS, LATENCY_THRESHOLDS, TPS_THRESHOLD, WORKLOAD_CATEGORY_IDS,
  describeGrade, formatMetricValue, roundForDisplay, type GradeRule, type GradeThreshold,
} from "@/lib/metricGrade";
import { HealthBadge } from "./MonitoringOverview";

interface Props {
  rows: MonitoringRow[];
  onToggleModel: (name: string) => void;
  selectedModels: Set<string>;
  now: number;
  grouped?: boolean;
}

const GRADES = ["normal", "warning", "critical"] as const;

/** 등급 규칙 → 툴팁 문구. 측정값 없음(none)은 문구 없음. */
function gradeHint(g: MetricGradeTexts, rule: GradeRule, metric: string): string | undefined {
  if (rule.grade === "none") return undefined;
  const scope = rule.lowerIsWorse ? g.allWorkloads : rule.category ? g.categories[rule.category] : g.defaultCategory;
  return g.hint({ grade: rule.grade, metric, scope, warnAt: rule.warnAt, critAt: rule.critAt, unit: rule.unit, lowerIsWorse: rule.lowerIsWorse });
}

/** 경고(▲)/위험(◆) 경계값 한 쌍 — 기준표 셀. 모양 표지는 스크린 리더에서 숨기고 대신 등급 이름을 읽어 준다. */
function ThresholdPair({ g, threshold, unit }: { g: MetricGradeTexts; threshold: GradeThreshold; unit: "ms" | "tok/s" }) {
  return (
    <span className="inline-flex flex-wrap gap-x-2 whitespace-nowrap">
      {(["warning", "critical"] as const).map((grade) => (
        <span key={grade} className={GRADE_TEXT_CLASS[grade]}>
          <span aria-hidden="true">{GRADE_MARKER[grade]} </span>
          <span className="sr-only">{g.names[grade]} </span>
          {g.threshold(grade === "warning" ? threshold.warn : threshold.crit, unit)}
        </span>
      ))}
    </span>
  );
}

/** 카드 값 색의 범례 + 접이식 기준표. 기준표는 모바일(툴팁 없음)에서도 경계를 확인할 수 있게 한다. */
function MetricGradeLegend() {
  const t = useT();
  const g = t.monitoring.grade;
  const rows = [
    ...WORKLOAD_CATEGORY_IDS.map((id) => ({ id, label: g.categories[id], thresholds: LATENCY_THRESHOLDS[id] })),
    { id: "fallback", label: g.defaultCategory, thresholds: FALLBACK_LATENCY_THRESHOLDS },
  ];
  return (
    <details className="group text-[11px] text-gray-500">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 [&::-webkit-details-marker]:hidden">
        <span className="sr-only">{g.legendLabel}:</span>
        {GRADES.map((grade) => (
          <span key={grade} className="inline-flex items-center gap-1">
            <span aria-hidden="true" className={GRADE_TEXT_CLASS[grade]}>{GRADE_MARKER[grade]}</span>
            <span className="text-gray-400">{g.names[grade]}</span>
          </span>
        ))}
        <span><span aria-hidden="true">— </span>{g.legendScope}</span>
        <span className="inline-flex items-center gap-1 text-gray-400">
          <span className="underline decoration-dotted underline-offset-2">{g.showCriteria}</span>
          <span aria-hidden="true" className="transition-transform group-open:rotate-180">▾</span>
        </span>
      </summary>
      <div className="mt-2 w-fit max-w-full overflow-x-auto rounded-lg border border-gray-800 bg-gray-900/50 p-3">
        <table className="w-full text-left tabular-nums">
          <thead>
            <tr className="text-gray-500">
              <th scope="col" className="pb-1 pr-4 font-medium">{t.workloadLabel}</th>
              <th scope="col" className="pb-1 pr-4 font-medium">TTFT</th>
              <th scope="col" className="pb-1 font-medium">{t.metrics.totalLatency.name}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t border-gray-800">
                <th scope="row" className="py-1 pr-4 font-normal text-gray-300">{row.label}</th>
                <td className="py-1 pr-4"><ThresholdPair g={g} threshold={row.thresholds.ttft} unit="ms" /></td>
                <td className="py-1"><ThresholdPair g={g} threshold={row.thresholds.total} unit="ms" /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 flex flex-wrap items-center gap-x-2 border-t border-gray-800 pt-2">
          <span className="text-gray-300">TPS ({g.allWorkloads})</span>
          <ThresholdPair g={g} threshold={TPS_THRESHOLD} unit="tok/s" />
        </p>
        <p className="mt-2 leading-relaxed">{g.criteriaNote}</p>
      </div>
    </details>
  );
}

export default function ModelStatusGrid({ rows, onToggleModel, selectedModels, now, grouped = true }: Props) {
  const t = useT();
  const { lang } = useLang();
  const m = t.monitoring;
  const idPrefix = useId();
  const groups = grouped ? groupByFamily(rows.map((row) => ({ ...row, model_name: row.model.name }))) : [rows];

  return (
    <div className="space-y-4">
      <MetricGradeLegend />
      {groups.map((group, groupIndex) => (
      <div key={group[0]?.model.id ?? "models"} className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {group.map(({ model, result, health, freshness }, index) => {
        const selected = selectedModels.has(model.name);
        const success = result?.status === "success";
        // 성공한 결과만 등급을 매긴다 — 값 텍스트 색은 워크로드 카테고리별 절대 기준(lib/metricGrade.ts).
        // 표시 정밀도로 반올림한 값으로 판정해 보이는 숫자와 색·툴팁이 어긋나지 않게 한다.
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
        const issuesId = issues.length ? `${idPrefix}-grade-${groupIndex}-${index}` : undefined;
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
              aria-describedby={issuesId}
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
                  {metrics.map((metric) => (
                    <span key={metric.key}>
                      <span className="block text-[11px] text-gray-500">{metric.name}</span>
                      <span
                        data-grade={metric.rule.grade}
                        title={metric.hint}
                        className={`mt-1 block font-mono text-base font-medium tabular-nums ${GRADE_TEXT_CLASS[metric.rule.grade]}`}
                      >
                        {metric.value}<span className="ml-1 text-[11px] font-normal text-gray-500">{metric.value !== "—" ? metric.unit : ""}</span>
                        {(metric.rule.grade === "warning" || metric.rule.grade === "critical") && (
                          <span aria-hidden="true" className="ml-1 align-[1px] text-[11px]">{GRADE_MARKER[metric.rule.grade]}</span>
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
              {/* 버튼 이름은 aria-label이라 내부 값이 읽히지 않는다 — 경고/위험 지표만 설명으로 연결 */}
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
      })}
      </div>
      ))}
    </div>
  );
}
