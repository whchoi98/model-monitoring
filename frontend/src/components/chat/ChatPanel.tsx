"use client";

import { useEffect, useState } from "react";
import { useChatStream } from "@/hooks/useChatStream";
import { fetchMe, getToken } from "@/lib/api";
import { AuthUser } from "@/lib/types";
import MessageList from "./MessageList";
import ChatInput from "./ChatInput";

interface ChatPanelProps {
  /** 헤더에 닫기 버튼을 노출할지 (modal에서는 노출, popup에서는 비노출). */
  onClose?: () => void;
  variant?: "modal" | "popup";
}

// 챗봇 본체 — modal과 popup 양쪽에서 재사용되는 공통 UI.
export default function ChatPanel({ onClose, variant = "modal" }: ChatPanelProps) {
  const { messages, isStreaming, error, send, cancel, reset } = useChatStream();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      setAuthChecked(true);
      return;
    }
    fetchMe()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
  }, []);

  if (!authChecked) {
    return (
      <div className="h-full flex items-center justify-center text-gray-500 text-sm">
        로그인 상태 확인 중...
      </div>
    );
  }

  if (!user) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-center gap-3 px-6">
        <div className="text-gray-300 text-sm">
          챗봇은 인증된 사용자만 사용할 수 있습니다.<br />
          대시보드에서 로그인 후 다시 시도해 주세요.
        </div>
        {variant === "modal" && onClose && (
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-xs rounded-md bg-gray-700 hover:bg-gray-600 text-white"
          >
            닫기
          </button>
        )}
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col bg-gray-900 text-gray-100">
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-emerald-500" />
          <span className="text-sm font-semibold">Bedrock Monitor Assistant</span>
          <span className="text-[10px] text-gray-500 uppercase tracking-wider">
            Sonnet 4.6
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={reset}
            className="text-xs text-gray-400 hover:text-gray-200"
          >
            새 대화
          </button>
          {variant === "modal" && onClose && (
            <button
              type="button"
              onClick={onClose}
              className="text-gray-400 hover:text-white text-lg leading-none px-1"
              aria-label="close"
            >
              ×
            </button>
          )}
        </div>
      </div>

      <MessageList messages={messages} isStreaming={isStreaming} />

      {error && (
        <div className="mx-3 mb-2 px-3 py-1.5 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-400">
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
