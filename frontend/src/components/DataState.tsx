"use client";

import type { ReactNode } from "react";
import { useT } from "@/lib/i18n-context";
import { ApiError } from "@/lib/http";

export function DataLoading({ label }: { label?: string }) {
  const t = useT();
  return (
    <div role="status" className="flex items-center gap-3 rounded-xl border border-gray-800 bg-gray-900/50 p-5 text-sm text-gray-400">
      <span aria-hidden="true" className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-blue-400 border-t-transparent" />
      {label ?? t.common.loading}
    </div>
  );
}

export function DataError({ error, resource, onRetry, hasData = false }: {
  error: Error | null;
  resource: string;
  onRetry: () => void;
  hasData?: boolean;
}) {
  const t = useT();
  if (!error) return null;
  const message = error.name === "TimeoutError" ? t.common.timeoutHint
    : error instanceof ApiError && (error.status === 401 || error.status === 403) ? t.common.authRequired
      : t.common.loadErrorHint;
  return (
    <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
      <div className="min-w-0">
        <p className="text-sm font-medium text-amber-300">{t.common.failedToLoad(resource)}</p>
        <p className="mt-1 text-xs leading-relaxed text-gray-400">{hasData ? t.common.lastGoodData : message}</p>
      </div>
      <button type="button" className="ui-button shrink-0" onClick={onRetry}>{t.common.retry}</button>
    </div>
  );
}

export function DataEmpty({ title, description, children }: { title?: string; description?: string; children?: ReactNode }) {
  const t = useT();
  return (
    <div role="status" className="rounded-xl border border-dashed border-gray-700 bg-gray-900/30 px-5 py-10 text-center">
      <p className="text-sm font-medium text-gray-300">{title ?? t.common.noData}</p>
      <p className="mt-2 text-xs leading-relaxed text-gray-500">{description ?? t.common.noDataHint}</p>
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}
