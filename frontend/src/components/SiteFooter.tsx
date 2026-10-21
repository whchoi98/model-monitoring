"use client";

import { useLang, useT } from "@/lib/i18n-context";
import { useVisitorCounts } from "@/lib/presence-context";
import { formatDateTime } from "@/lib/format";
import { APP_VERSION } from "@/lib/version";

export default function SiteFooter() {
  const { lang } = useLang();
  const t = useT();
  const p = t.presence;
  const { snapshot, status } = useVisitorCounts();
  const locale = lang === "ko" ? "ko-KR" : "en-US";
  const active = status === "live" && snapshot ? snapshot.active_visitors.toLocaleString(locale) : "—";
  const total = snapshot ? snapshot.total_visitors.toLocaleString(locale) : "—";
  return (
    <footer aria-label={p.title} data-presence-state={status}
      className="site-footer mx-auto mt-8 border-t border-gray-800 pt-6 [padding-bottom:max(6rem,var(--comparison-dock-clearance,0px))] sm:[padding-bottom:max(7rem,var(--comparison-dock-clearance,0px))]">
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 text-xs">
        <span className="text-gray-500">LLM Monitor <span className="ml-1">{APP_VERSION}</span></span>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          {status !== "live" && <span className="text-xs text-gray-500">{status === "loading" ? p.loading : status === "stale" ? p.stale : p.unavailable}</span>}
          <dl className="flex flex-wrap gap-x-4 gap-y-2">
            <div className="flex items-center gap-2">
              <dt className="inline-flex items-center gap-1.5 text-gray-400">
                <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${status === "live" ? "bg-emerald-400" : "bg-gray-500"}`} />
                {p.active}
              </dt>
              <dd className="font-semibold tabular-nums text-gray-200">{active}</dd>
            </div>
            <div className="flex items-center gap-2">
              <dt className="text-gray-400">{p.total}</dt>
              <dd className="font-semibold tabular-nums text-gray-200">{total}</dd>
            </div>
          </dl>
        </div>
      </div>
      <details className="mt-2 text-xs text-gray-500">
        <summary className="w-fit cursor-pointer rounded py-2">{p.about}</summary>
        <div className="ui-copy max-w-3xl space-y-1 leading-relaxed">
          <p>{p.criteria}</p>
          <p>{p.refreshHint}</p>
          {snapshot && <p>{t.common.updatedAt}: <time dateTime={snapshot.as_of}>{formatDateTime(snapshot.as_of, lang)}</time></p>}
        </div>
      </details>
    </footer>
  );
}
