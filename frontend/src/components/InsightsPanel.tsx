"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchLatestInsight,
  streamRegenerateInsight,
} from "@/lib/api";
import { Insight } from "@/lib/types";
import { useLang } from "@/lib/i18n-context";
import { useAuth } from "@/lib/auth-context";
import MessageMarkdown from "./chat/MessageMarkdown";

// 인사이트 위젯 - 최신 인사이트 표시 + (인증 후) SSE 스트리밍 재생성.
// 검색은 채팅봇에서 대신 수행 (제거).
export default function InsightsPanel() {
  const { lang } = useLang();

  const [insight, setInsight] = useState<Insight | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [streamingText, setStreamingText] = useState<string>("");
  const { user, checking, openLogin } = useAuth();
  const authed = user !== null;

  const load = useCallback(async () => {
    try {
      const d = await fetchLatestInsight();
      setInsight(d);
    } catch {
      setInsight(null);
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
          // 스트리밍 종료 후 latest fetch로 DB-saved Insight 가져오기.
          fetchLatestInsight().then(setInsight).catch(() => {});
        },
        onError: (err) => {
          setRegenerating(false);
          setStatusMsg(`${err.message}`);
          setStreamingText("");
          setTimeout(() => setStatusMsg(null), 5000);
        },
      },
    );
  };

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
          <span aria-hidden>✨</span>
          {lang === "en" ? "AI Insights" : "AI 인사이트"}
        </h3>
        <div className="flex items-center gap-3">
          {insight && (
            <span className="text-[10px] text-gray-500">
              {new Date(insight.created_at).toLocaleString(lang === "en" ? "en-US" : "ko-KR")}
            </span>
          )}
          {authed ? (
            <button
              type="button"
              onClick={handleRegenerate}
              disabled={regenerating || checking}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-blue-600/80 hover:bg-blue-500 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              title={
                lang === "en"
                  ? "Regenerate insight now (10-30s)"
                  : "현재 데이터로 즉시 인사이트 재생성 (10~30초)"
              }
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                className={`w-3.5 h-3.5 ${regenerating ? "animate-spin" : ""}`}
              >
                <path d="M21 12a9 9 0 11-9-9c2.5 0 4.7 1 6.4 2.6L21 8" />
                <path d="M21 3v5h-5" />
              </svg>
              {regenerating
                ? lang === "en"
                  ? "Generating"
                  : "생성 중"
                : lang === "en"
                  ? "Refresh"
                  : "새로고침"}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => openLogin()}
              disabled={checking}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-gray-700 hover:bg-gray-600 text-white transition-colors"
              title={
                lang === "en"
                  ? "Login required to refresh / search"
                  : "새로고침/검색은 로그인 후 사용 가능"
              }
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="w-3.5 h-3.5"
              >
                <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4M10 17l5-5-5-5M15 12H3" />
              </svg>
              {lang === "en" ? "Login" : "로그인"}
            </button>
          )}
        </div>
      </div>

      {/* Status message */}
      {statusMsg && (
        <div className="px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-blue-300">
          {statusMsg}
        </div>
      )}

      {/* Latest insight content - 스트리밍 중이면 streamingText, 아니면 저장된 insight */}
      {loading ? (
        <div className="text-xs text-gray-500">{lang === "en" ? "Loading..." : "로딩 중..."}</div>
      ) : streamingText ? (
        <div className="border-l-2 border-blue-500/50 pl-3">
          <MessageMarkdown text={streamingText} />
          <div className="text-[10px] text-blue-400/70 mt-2 animate-pulse">
            {lang === "en" ? "Streaming from Sonnet 4.6..." : "Sonnet 4.6 스트리밍 중..."}
          </div>
        </div>
      ) : insight ? (
        <div>
          <MessageMarkdown
            text={
              lang === "en" && insight.summary_md_en
                ? insight.summary_md_en
                : insight.summary_md
            }
          />
        </div>
      ) : (
        <div className="text-xs text-gray-500">
          {lang === "en"
            ? "No insight yet. Click Refresh (login required) or wait for the next 5-min job."
            : "아직 생성된 인사이트가 없습니다. \"새로고침\" 버튼으로 즉시 생성하거나 5분 주기 잡을 기다리세요."}
        </div>
      )}

    </div>
  );
}
