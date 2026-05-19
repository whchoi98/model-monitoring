"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchLatestInsight, regenerateInsight } from "@/lib/api";
import { Insight } from "@/lib/types";
import MessageMarkdown from "./chat/MessageMarkdown";

// 대시보드용 위젯 - 가장 최근 인사이트 + 즉시 재생성 버튼.
// insights_runner가 10분마다 자동 갱신. 사용자가 즉시 재생성 원할 시 새로고침 버튼.
export default function InsightsPanel() {
  const [insight, setInsight] = useState<Insight | null>(null);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

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
    const id = setInterval(load, 60_000); // 1분마다 폴링 (10분 주기 잡 신선도 유지)
    return () => clearInterval(id);
  }, [load]);

  const handleRegenerate = async () => {
    if (regenerating) return;
    setRegenerating(true);
    setStatusMsg("인사이트 생성 요청 중...");
    try {
      const r = await regenerateInsight("6h");
      if (!r.triggered) {
        setStatusMsg(r.message);
        // 이미 진행 중이면 새 결과 기다림
      } else {
        setStatusMsg("Sonnet 4.6이 데이터를 분석 중입니다 (보통 10~30초 소요)...");
      }

      // 백엔드는 비동기로 실행 — 결과 폴링 (최대 60초)
      const startId = insight?.id ?? 0;
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const latest = await fetchLatestInsight().catch(() => null);
        if (latest && latest.id !== startId) {
          setInsight(latest);
          setStatusMsg(null);
          break;
        }
      }
    } catch (err) {
      setStatusMsg(`생성 실패: ${(err as Error).message}`);
    } finally {
      setRegenerating(false);
      // 메시지는 잠시 후 자동 정리
      setTimeout(() => setStatusMsg(null), 5000);
    }
  };

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
          <span aria-hidden>✨</span>
          AI 인사이트
        </h3>
        <div className="flex items-center gap-3">
          {insight && (
            <span className="text-[10px] text-gray-500">
              {new Date(insight.created_at).toLocaleString("ko-KR")}
            </span>
          )}
          <button
            type="button"
            onClick={handleRegenerate}
            disabled={regenerating}
            className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md bg-blue-600/80 hover:bg-blue-500 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            title="현재 데이터로 즉시 새 인사이트를 생성합니다 (10초~30초 소요)"
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
            {regenerating ? "생성 중" : "새로고침"}
          </button>
        </div>
      </div>

      {statusMsg && (
        <div className="mb-2 px-3 py-1.5 bg-blue-500/10 border border-blue-500/30 rounded text-xs text-blue-300">
          {statusMsg}
        </div>
      )}

      {loading ? (
        <div className="text-xs text-gray-500">로딩 중...</div>
      ) : insight ? (
        <div className="max-h-72 overflow-y-auto">
          <MessageMarkdown text={insight.summary_md} />
        </div>
      ) : (
        <div className="text-xs text-gray-500">
          아직 생성된 인사이트가 없습니다. &quot;새로고침&quot; 버튼으로 즉시 생성하거나 10분 주기 잡을 기다리세요.
        </div>
      )}
    </div>
  );
}
