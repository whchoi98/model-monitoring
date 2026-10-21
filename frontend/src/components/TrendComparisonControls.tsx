"use client";

import { useMemo } from "react";
import { useT } from "@/lib/i18n-context";
import { FAMILY_ORDER, familyRank, groupByFamily } from "@/lib/sortModels";
import { defaultTrendSelection } from "@/lib/trendSelection";

export default function TrendComparisonControls({ availableModels, selectedModels, onSelect }: {
  availableModels: string[];
  selectedModels: Set<string>;
  onSelect: (names: Set<string>) => void;
}) {
  const t = useT();
  const m = t.monitoring;
  const groups = useMemo(() => groupByFamily(availableModels.map((model_name) => ({ model_name }))).map((group) => ({
    key: FAMILY_ORDER[familyRank(group[0].model_name)] ?? "other",
    names: group.map((row) => row.model_name),
  })), [availableModels]);
  const representatives = useMemo(() => defaultTrendSelection(availableModels), [availableModels]);
  const isSelection = (names: Iterable<string>, count: number) => count > 0 && count === selectedModels.size && Array.from(names).every((name) => selectedModels.has(name));
  const family = groups.find((group) => isSelection(group.names, group.names.length))?.key ?? "";
  const representativeSelection = isSelection(representatives, representatives.size);

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-gray-800 bg-gray-900/50 p-3">
      <div role="group" aria-label={m.comparisonScope} className="flex flex-wrap items-center gap-2">
        <button type="button" className={selectedModels.size === 0 ? "ui-button-primary" : "ui-button"}
          aria-pressed={selectedModels.size === 0} onClick={() => onSelect(new Set())}>{t.allModels}</button>
        <button type="button" className={representativeSelection ? "ui-button-primary" : "ui-button"}
          aria-pressed={representativeSelection} disabled={!representatives.size}
          onClick={() => onSelect(representatives)}>{t.repModels}</button>
      </div>
      <label className="min-w-0 flex-1 sm:max-w-xs">
        <span className="sr-only">{m.familyCompare}</span>
        <select className="ui-input w-full text-xs" value={family} onChange={(event) => {
          const group = groups.find((candidate) => candidate.key === event.target.value);
          if (group) onSelect(new Set(group.names));
        }}>
          <option value="">{m.chooseFamily}</option>
          {groups.map((group) => <option key={group.key} value={group.key}>{group.key === "other" ? m.otherModels : group.key} · {m.channelCount(group.names.length)}</option>)}
        </select>
      </label>
      <p className="ui-copy w-full text-[11px] text-gray-500">
        {t.repModelsHint}{selectedModels.size > 0 ? ` · ${m.selection(selectedModels.size)}` : ""}
      </p>
    </div>
  );
}
