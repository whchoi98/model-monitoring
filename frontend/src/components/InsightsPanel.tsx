"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchLatestInsight,
  streamRegenerateInsight,
} from "@/lib/api";
import { Insight } from "@/lib/types";
import { useLang, useT } from "@/lib/i18n-context";
import { useAuth } from "@/lib/auth-context";
import MessageMarkdown from "./chat/MessageMarkdown";
import { DataError } from "./DataState";

// 인사이트 위젯 - 최신 인사이트 표시 + (인증 후) SSE 스트리밍 재생성.
// 검색은 채팅봇에서 대신 수행 (제거).
export default function InsightsPanel() {
  const { lang } = useLang();
  const t = useT();
  const [expanded, setExpanded] = useState(false);

  const [insight, setInsight] = useState<Insight | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [generationError, setGenerationError] = useState<string | null>(null);
  const [regenerating, setRegenerating] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState<string>("");
  const { user, checking, openLogin } = useAuth();
  const authed = user !== null;

  const load = useCallback(async () => {
    try {
      const d = await fetchLatestInsight();
      setInsight(d);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error : new Error(String(error)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, [load]);

  const handleRegenerate = () => {
    if (regenerating || checking) return;
    if (!authed) {
      openLogin();
      return;
    }
    setRegenerating(true);
    setGenerationError(null);
    setStreamingText("");
    setStatusMsg(lang === "en" ? "Streaming..." : "스트리밍 중...");
    streamRegenerateInsight(
      { window: "6h", lang },
      {
        onDelta: (t) => setStreamingText((prev) => prev + t),
        onFinal: (payload) => {
          setRegenerating(false);
          setStatusMsg(null);
          setStreamingText("");
          if (!payload.ok) {
            setGenerationError(payload.error || (lang === "en" ? "Unable to save the analysis. Please try again." : "분석을 저장하지 못했습니다. 다시 시도해 주세요."));
            return;
          }
          void load();
        },
        onError: (err) => {
          setRegenerating(false);
          setStatusMsg(null);
          setGenerationError(err.message);
          setStreamingText("");
        },
      },
    );
  };

  return (
    <section id="ai-insights" aria-label={lang === "en" ? "AI Insights" : "AI 인사이트"} className="ui-panel space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="page-eyebrow">SONNET 5.5</p>
          <h2 className="text-base font-semibold text-gray-100">{lang === "en" ? "AI Insights" : "AI 인사이트"}</h2>
        </div>
        <button type="button" className={authed ? "ui-button-primary" : "ui-button"}
          onClick={handleRegenerate} disabled={regenerating || checking}
          aria-label={lang === "en" ? (authed ? "Refresh AI insights" : "Sign in for AI insights") : (authed ? "AI 분석 새로고침" : "AI 분석을 위해 로그인")}>
          {regenerating ? (lang === "en" ? "Generating" : "생성 중") : authed ? t.common.refresh : (lang === "en" ? "Login" : "로그인")}
        </button>
      </div>
      <p className="ui-copy text-xs leading-relaxed text-gray-500">{t.workspace.insightsDescription}</p>
      {insight && <p className="text-xs text-gray-500">
        {new Date(insight.created_at).toLocaleString(lang === "en" ? "en-US" : "ko-KR")}
      </p>}

      {/* Status message */}
      {statusMsg && (
        <div className="px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-blue-300">
          {statusMsg}
        </div>
      )}

      <DataError error={loadError} resource={lang === "en" ? "AI insights" : "AI 인사이트"} onRetry={() => void load()} hasData={!!insight} />
      {generationError && <p role="alert" className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-300">{generationError}</p>}
      <div id="insight-body">
      {loading ? (
        <div className="text-xs text-gray-500">{lang === "en" ? "Loading..." : "로딩 중..."}</div>
      ) : streamingText ? (
        <div className="border-l-2 border-blue-500/50 pl-3">
          <MessageMarkdown text={streamingText} />
          <div className="text-xs text-blue-400/70 mt-2 animate-pulse">
            {lang === "en" ? "Streaming from Sonnet 5.5..." : "Sonnet 5.5 스트리밍 중..."}
          </div>
        </div>
      ) : insight ? (
        expanded ? <MessageMarkdown text={lang === "en" && insight.summary_md_en ? insight.summary_md_en : insight.summary_md} /> : (
          <p className="ui-copy text-sm leading-relaxed text-gray-300">
            {(lang === "en" && insight.summary_md_en ? insight.summary_md_en : insight.summary_md)
              .replace(/```[\s\S]*?```/g, "")
              .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
              .replace(/^[\s#>*-]+/gm, "").replace(/[*_`|]/g, "")
              .replace(/\s+/g, " ").trim().slice(0, 160)}
            {(lang === "en" && insight.summary_md_en ? insight.summary_md_en : insight.summary_md).length > 160 ? "…" : ""}
          </p>
        )
      ) : loadError ? null : (
        <div className="text-xs text-gray-500">
          {lang === "en"
            ? "No insight yet. Click Refresh (login required) or wait for the next 5-min job."
            : "아직 생성된 인사이트가 없습니다. \"새로고침\" 버튼으로 즉시 생성하거나 5분 주기 잡을 기다리세요."}
        </div>
      )}

      </div>
      {insight && !streamingText && (
        <button type="button" className="ui-button w-full" aria-expanded={expanded}
          aria-controls="insight-body" onClick={() => setExpanded((value) => !value)}>
          {expanded ? t.workspace.collapseInsight : t.workspace.expandInsight}
        </button>
      )}
    </section>
  );
}
