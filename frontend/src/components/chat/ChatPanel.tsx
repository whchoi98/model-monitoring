"use client";

import { useChatStream } from "@/hooks/useChatStream";
import { useLang } from "@/lib/i18n-context";
import MessageList from "./MessageList";
import ChatInput from "./ChatInput";

// 인사이트가 있는 추천 풍선말 — 각 메뉴(분석/비용/효율성/신뢰성)의 핵심 질문을 노출.
// 자주 묻는 가벼운 질문 + 새 기능(분석)의 강력한 질문을 균형 있게 배치.
const SUGGESTED_KO = [
  "이번 주 가장 비용 효율적인 모델 추천해줘",
  "max_tokens로 잘린 응답이 많은 모델은?",
  "같은 워크로드에서 출력 길이가 가장 짧은 모델은?",
  "Global vs US 채널 중 어느 쪽이 더 안정적이야?",
  "지난 24시간 효율성 점수(Top 3) 알려줘",
  "최근에 에러가 발생한 모델과 원인은?",
];
const SUGGESTED_EN = [
  "Which model is most cost-efficient this week?",
  "Which models often hit max_tokens (truncated)?",
  "Which model gives the shortest output for the same workload?",
  "Is Global or US channel more reliable?",
  "Top 3 efficiency scores in the last 24h",
  "What models errored recently and why?",
];
const FOLLOWUP_KO = [
  "그 모델의 p95 지연시간은?",
  "최근 1시간 vs 24시간 변화 추이는?",
  "에러 원인 분석해줘",
  "비슷한 다른 모델도 비교해줘",
];
const FOLLOWUP_EN = [
  "What is its p95 latency?",
  "Show 1h vs 24h trend",
  "Analyze the error cause",
  "Compare with similar models",
];

interface ChatPanelProps {
  /** 헤더에 닫기 버튼을 노출할지 (modal에서는 노출, popup에서는 비노출). */
  onClose?: () => void;
  variant?: "modal" | "popup";
}

// 챗봇 본체 — modal과 popup 양쪽에서 재사용되는 공통 UI.
export default function ChatPanel({ onClose, variant = "modal" }: ChatPanelProps) {
  const { messages, isStreaming, error, followups, send, cancel, reset } = useChatStream();
  const { lang } = useLang();

  const suggested = lang === "en" ? SUGGESTED_EN : SUGGESTED_KO;
  // 동적 followups가 있으면 사용, 없으면 (초기 상태) 정적 fallback 사용.
  const followUps = followups.length > 0 ? followups : (lang === "en" ? FOLLOWUP_EN : FOLLOWUP_KO);
  const handleSuggested = (q: string) => {
    if (isStreaming) return;
    send(q);
  };

  return (
    <div className="chat-panel h-full min-w-0 flex flex-col bg-gray-900 text-gray-100">
      <div className="chat-panel-heading flex items-start justify-between gap-3 border-b border-gray-800 px-4 py-4">
        <div className="min-w-0">
          <span className="mb-1 block text-xs font-semibold text-blue-400">Haiku 5.5</span>
          <span className="block text-sm font-semibold">{lang === "en" ? "Bedrock Monitor Assistant" : "모니터링 AI 어시스턴트"}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={reset}
            className="ui-button whitespace-nowrap"
          >
            {lang === "en" ? "New chat" : "새 대화"}
          </button>
          {variant === "modal" && onClose && (
            <button
              type="button"
              onClick={onClose}
              className="ui-button min-w-10 px-2 text-lg leading-none"
              aria-label={lang === "en" ? "Close chat" : "챗봇 닫기"}
            >
              ×
            </button>
          )}
        </div>
      </div>

      <MessageList
        messages={messages}
        isStreaming={isStreaming}
        suggested={suggested}
        followUps={followUps}
        onSuggested={handleSuggested}
        emptyHint={
          lang === "en"
            ? "Ask me about Bedrock model performance."
            : "Bedrock 모델 성능에 대해 질문하세요."
        }
        suggestedLabel={lang === "en" ? "Suggested" : "추천 검색어"}
        followUpLabel={lang === "en" ? "Follow up" : "이어서 물어보기"}
      />

      {error && (
        <div role="alert" className="mx-3 mb-2 px-3 py-1.5 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-400">
          {error}
        </div>
      )}

      <ChatInput
        disabled={isStreaming}
        isStreaming={isStreaming}
        onSubmit={send}
        onCancel={cancel}
      />
    </div>
  );
}
