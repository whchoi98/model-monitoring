"use client";

import { useEffect, useState } from "react";
import { fetchLatestInsight } from "@/lib/api";
import { Insight } from "@/lib/types";
import MessageMarkdown from "./chat/MessageMarkdown";

// 대시보드용 위젯 — 가장 최근의 인사이트 1건을 표시.
// insights_runner가 30분마다 갱신.
export default function InsightsPanel() {
  const [insight, setInsight] = useState<Insight | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const load = () =>
      fetchLatestInsight()
        .then((d) => alive && setInsight(d))
        .catch(() => alive && setInsight(null))
        .finally(() => alive && setLoading(false));
    load();
    // 5분마다 자동 갱신.
    const id = setInterval(load, 5 * 60 * 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
          <span aria-hidden>✨</span>
          AI 인사이트
        </h3>
        {insight && (
          <span className="text-[10px] text-gray-500">
            {new Date(insight.created_at).toLocaleString("ko-KR")}
          </span>
        )}
      </div>
      {loading ? (
        <div className="text-xs text-gray-500">로딩 중...</div>
      ) : insight ? (
        <div className="max-h-72 overflow-y-auto">
          <MessageMarkdown text={insight.summary_md} />
        </div>
      ) : (
        <div className="text-xs text-gray-500">
          아직 생성된 인사이트가 없습니다. 자동 잡이 처음 실행될 때까지 대기 중입니다.
        </div>
      )}
    </div>
  );
}
