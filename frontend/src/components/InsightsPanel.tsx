"use client";

import { useEffect, useRef, useState } from "react";
import { fetchLatestInsight, streamRegenerateInsight } from "@/lib/api";
import { useLang, useT } from "@/lib/i18n-context";
import { useAuth } from "@/lib/auth-context";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { formatDateTime } from "@/lib/format";
import MessageMarkdown from "./chat/MessageMarkdown";
import { DataError } from "./DataState";
import FloatingWindow from "./FloatingWindow";

export default function InsightsPanel() {
  const { lang } = useLang();
  const t = useT();
  const title = lang === "en" ? "AI Insights" : "AI 인사이트";
  const [open, setOpen] = useState(false);
  const resource = useAsyncResource("latest-insight", fetchLatestInsight);
  const { data: insight, error: loadError, loading, refreshing, refresh } = resource;
  useAutoRefresh(refresh, 60_000);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const request = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const { user, checking } = useAuth();

  useEffect(() => () => { generation.current++; request.current?.abort(); }, []);

  const handleRegenerate = () => {
    if (regenerating || checking || !user) return;
    const current = ++generation.current;
    const active = () => generation.current === current;
    setRegenerating(true);
    setGenerationError(null);
    setStreamingText("");
    request.current = streamRegenerateInsight({ window: "6h", lang }, {
      onDelta: text => { if (active()) setStreamingText(previous => previous + text); },
      onFinal: payload => {
        if (!active()) return;
        setRegenerating(false);
        setStreamingText("");
        if (!payload.ok) {
          setGenerationError(payload.error || (lang === "en" ? "Unable to save the analysis. Please try again." : "분석을 저장하지 못했습니다. 다시 시도해 주세요."));
          return;
        }
        void refresh();
      },
      onError: error => {
        if (!active()) return;
        setRegenerating(false);
        setGenerationError(error.message);
        setStreamingText("");
      },
    });
  };

  const summary = streamingText || (lang === "en" && insight?.summary_md_en ? insight.summary_md_en : insight?.summary_md) || "";
  const preview = summary.replace(/```[\s\S]*?```/g, "").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/^[\s#>*-]+/gm, "").replace(/[*_`|]/g, "").replace(/\s+/g, " ").trim();
  const created = insight && formatDateTime(insight.created_at, lang);
  const errors = <>
    <DataError error={loadError} resource={title} onRetry={() => void refresh()} hasData={!!insight} />
    {generationError && <p role="alert" className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300">{generationError}</p>}
  </>;
  const refreshButton = (
    <button type="button" className="ui-button" onClick={() => void refresh()} disabled={refreshing}
      aria-label={lang === "en" ? "Refresh AI insights" : "AI 인사이트 새로고침"} aria-busy={refreshing}>
      {refreshing ? t.common.refreshing : t.common.refresh}
    </button>
  );

  return (
    <>
      <section id="ai-insights" aria-label={title} className="ui-panel space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="page-eyebrow">HAIKU 5.5</p>
            <h2 className="text-base font-semibold text-gray-100">{title}</h2>
          </div>
          <div className="flex items-center gap-1">
            {refreshButton}
            <button type="button" className="window-control" aria-haspopup="dialog"
              aria-label={lang === "en" ? "Expand AI insights" : "AI 인사이트 확대"} onClick={() => setOpen(true)}>
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M14 4h6v6m-6 0 6-6M10 20H4v-6m6 0-6 6" /></svg>
            </button>
          </div>
        </div>
        <p className="ui-copy text-xs leading-relaxed text-gray-500">{t.workspace.insightsDescription}</p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-gray-500">
          <span className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-blue-500" />{lang === "en" ? "Analyzed every 5 min" : "5분마다 자동 분석"}</span>
          {created && <time dateTime={insight!.created_at}>{created}</time>}
        </div>
        {errors}
        {regenerating && <p role="status" className="text-xs text-blue-400">{lang === "en" ? "Haiku 5.5 is analyzing the latest results…" : "Haiku 5.5가 최신 결과를 분석하고 있습니다…"}</p>}
        {loading ? <p className="text-xs text-gray-500">{t.common.loading}</p>
          : summary ? <p className="ui-copy text-sm leading-relaxed text-gray-300">{preview.slice(0, 180)}{preview.length > 180 ? "…" : ""}</p>
          : !loadError && <p className="text-xs text-gray-500">{lang === "en" ? "No insight yet. The next automatic analysis will appear here." : "아직 생성된 인사이트가 없습니다. 다음 자동 분석이 완료되면 여기에 표시됩니다."}</p>}
        {summary && <button type="button" className="ui-button w-full" aria-haspopup="dialog" onClick={() => setOpen(true)}>
          {t.workspace.expandInsight}<span aria-hidden="true" className="ml-2">↗</span>
        </button>}
      </section>
      <FloatingWindow open={open} onClose={() => setOpen(false)} title={title} className="insights-window">
        <div className="insights-reading-view">
          <div className="insights-reading-toolbar">
            <div>
              <p className="page-eyebrow mb-1">HAIKU 5.5</p>
              <p className="text-xs text-gray-500">{created || (lang === "en" ? "Analyzed every 5 min" : "5분마다 자동 분석")}</p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              {refreshButton}
              {user && <button type="button" className="ui-button-primary" onClick={handleRegenerate} disabled={regenerating || checking}>
                {regenerating ? (lang === "en" ? "Generating…" : "생성 중…") : (lang === "en" ? "Generate new analysis" : "새 분석 생성")}
              </button>}
            </div>
          </div>
          <div className="insights-reading-body" tabIndex={0} aria-label={lang === "en" ? "Full analysis" : "전체 분석"}>
            {errors}
            {regenerating && <p role="status" className="mb-4 text-sm text-blue-400">{lang === "en" ? "Haiku 5.5 is analyzing the latest results…" : "Haiku 5.5가 최신 결과를 분석하고 있습니다…"}</p>}
            {summary ? <MessageMarkdown text={summary} /> : <p className="text-sm text-gray-500">{loading ? t.common.loading : lang === "en" ? "The next automatic analysis will appear here." : "다음 자동 분석이 완료되면 여기에 표시됩니다."}</p>}
          </div>
        </div>
      </FloatingWindow>
    </>
  );
}
