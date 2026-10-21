"use client";

import { memo, useId, useMemo, useState } from "react";
import { useT } from "@/lib/i18n-context";
import type { MetricGradeTexts } from "@/lib/i18n";
import type { MonitoringRow } from "@/lib/monitoring";
import { FAMILY_ORDER, familyRank, groupByFamily } from "@/lib/sortModels";
import {
  FALLBACK_LATENCY_THRESHOLDS, GRADE_MARKER, GRADE_TEXT_CLASS, LATENCY_THRESHOLDS, TPS_THRESHOLD, WORKLOAD_CATEGORY_IDS,
  type GradeThreshold,
} from "@/lib/metricGrade";
import ModelStatusItem, { type ModelLayout } from "./ModelStatusItem";

interface Props {
  rows: MonitoringRow[];
  onToggleModel: (name: string) => void;
  selectedModels: Set<string>;
  now: number;
  grouped?: boolean;
  layout?: ModelLayout;
  onCompareFamily?: (names: string[]) => void;
}

const GRADES = ["normal", "warning", "critical"] as const;

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
    <details className="group text-xs text-gray-500">
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 [&::-webkit-details-marker]:hidden">
        <span className="font-medium text-gray-400">{g.legendLabel}:</span>
        {GRADES.map((grade) => (
          <span key={grade} className="hidden items-center gap-1 group-open:inline-flex sm:inline-flex">
            {/* 카드와 같은 규칙: 경고/위험 값에만 모양 표지가 붙으므로 양호는 모양 없는 색 견본만 보여 준다. */}
            {GRADE_MARKER[grade] ? (
              <span aria-hidden="true" className={GRADE_TEXT_CLASS[grade]}>{GRADE_MARKER[grade]}</span>
            ) : (
              <span aria-hidden="true" data-swatch={grade} className={`inline-block h-2 w-2 rounded-[2px] bg-current ${GRADE_TEXT_CLASS[grade]}`} />
            )}
            <span className="text-gray-400">{g.names[grade]}</span>
          </span>
        ))}
        <span className="hidden group-open:inline sm:inline"><span aria-hidden="true">— </span>{g.legendScope}</span>
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

function ModelStatusGrid({ rows, onToggleModel, selectedModels, now, grouped = true, layout = "compact", onCompareFamily }: Props) {
  const t = useT();
  const m = t.monitoring;
  const idPrefix = useId();
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set());
  const groups = useMemo(
    () => grouped ? groupByFamily(rows.map((row) => ({ ...row, model_name: row.model.name }))) : [rows],
    [rows, grouped],
  );
  const familyKey = (group: MonitoringRow[]) => FAMILY_ORDER[familyRank(group[0]?.model.name ?? "")] ?? "other";
  const allCollapsed = groups.length > 0 && groups.every((group) => collapsed.has(familyKey(group)));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <MetricGradeLegend />
        {grouped && (
          <button type="button" className="ui-button shrink-0" onClick={() => setCollapsed(allCollapsed ? new Set() : new Set(groups.map(familyKey)))}>
            {allCollapsed ? m.expandFamilies : m.collapseFamilies}
          </button>
        )}
      </div>
      {layout === "compact" && (
        <div aria-hidden="true" className="hidden grid-cols-[minmax(0,1fr)_21rem] gap-6 px-4 text-xs font-medium text-gray-500 md:grid">
          <span>{m.modelChannel}</span>
          <div className="grid grid-cols-3 gap-2"><span>TTFT</span><span>{t.metrics.totalLatency.name}</span><span>TPS</span></div>
        </div>
      )}
      {groups.map((group, groupIndex) => (
        <div key={grouped ? familyKey(group) : "flat"} className="space-y-2">
          {grouped && (
            <div className="flex items-center justify-between gap-3">
              <h3 className="min-w-0 flex-1">
                <button
                  type="button"
                  className="flex min-h-10 w-full flex-wrap items-center gap-x-2 gap-y-1 rounded-lg py-1 text-left"
                  aria-label={m.familyChannels(familyKey(group) === "other" ? m.otherModels : familyKey(group))}
                  aria-expanded={!collapsed.has(familyKey(group))}
                  aria-controls={`${idPrefix}-family-${groupIndex}`}
                  onClick={() => setCollapsed((previous) => {
                    const next = new Set(previous);
                    if (next.has(familyKey(group))) next.delete(familyKey(group));
                    else next.add(familyKey(group));
                    return next;
                  })}
                >
                  <span aria-hidden="true" className="w-3 text-xs text-gray-500">{collapsed.has(familyKey(group)) ? "▸" : "▾"}</span>
                  <span className="text-sm font-semibold text-gray-200">{familyKey(group) === "other" ? m.otherModels : familyKey(group)}</span>
                  <span className="text-xs font-normal text-gray-500">{m.channelCount(group.length)}</span>
                  {group.some((row) => row.health !== "healthy") && (
                    <span className="whitespace-nowrap text-xs font-normal text-amber-300">{m.attentionCount(group.filter((row) => row.health !== "healthy").length)}</span>
                  )}
                </button>
              </h3>
              {onCompareFamily && (
                <button type="button" className="ui-button shrink-0"
                  aria-label={m.compareFamily(familyKey(group) === "other" ? m.otherModels : familyKey(group))}
                  onClick={() => onCompareFamily(group.map((row) => row.model.name))}>
                  {m.compareChannels}
                </button>
              )}
            </div>
          )}
          <div id={`${idPrefix}-family-${groupIndex}`}
            className={grouped && collapsed.has(familyKey(group)) ? "hidden" : layout === "cards" ? "grid grid-cols-1 gap-3 md:grid-cols-2 2xl:grid-cols-3" : "grid grid-cols-1 gap-1.5"}>
            {group.map((row) => (
              <ModelStatusItem key={row.model.id} row={row} selected={selectedModels.has(row.model.name)}
                onToggleModel={onToggleModel} now={now} layout={layout} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export default memo(ModelStatusGrid);
