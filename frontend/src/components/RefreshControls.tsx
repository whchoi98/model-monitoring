"use client";

import { useLang, useT } from "@/lib/i18n-context";
import { formatDateTime } from "@/lib/format";

export default function RefreshControls({
  refreshing, onRefresh, updatedAt, enabled, onEnabledChange, countdown,
}: {
  refreshing: boolean;
  onRefresh: () => void;
  updatedAt: number | null;
  enabled?: boolean;
  onEnabledChange?: (enabled: boolean) => void;
  countdown?: number;
}) {
  const t = useT();
  const { lang } = useLang();
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
      <span className="text-gray-500" title={updatedAt ? formatDateTime(updatedAt, lang) : undefined}>
        {t.common.updatedAt}: <span className="tabular-nums text-gray-400">{updatedAt ? formatDateTime(updatedAt, lang) : t.common.notUpdated}</span>
      </span>
      {onEnabledChange && (
        <label className="flex min-h-9 cursor-pointer items-center gap-2 text-gray-400">
          <input type="checkbox" checked={enabled} onChange={(event) => onEnabledChange(event.target.checked)} className="h-4 w-4 accent-blue-600" />
          {t.common.autoRefresh}
          <span className="min-w-8 tabular-nums text-gray-500">{enabled ? `${countdown ?? 30}s` : t.common.paused}</span>
        </label>
      )}
      <button type="button" onClick={onRefresh} disabled={refreshing} className="ui-button" aria-label={t.common.refresh}>
        <svg aria-hidden="true" className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20 7v5h-5M4 17v-5h5M6.1 6.1A8 8 0 0119.6 10M4.4 14A8 8 0 0017.9 17.9" />
        </svg>
        {refreshing ? t.common.refreshing : t.common.refresh}
      </button>
    </div>
  );
}
