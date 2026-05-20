"use client";

import { useEffect, useRef } from "react";
import { ChatMessage } from "@/lib/types";
import MessageMarkdown from "./MessageMarkdown";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
  suggested?: string[];
  followUps?: string[];
  onSuggested?: (q: string) => void;
  emptyHint?: string;
  suggestedLabel?: string;
  followUpLabel?: string;
}

// 메시지 리스트 — 자동 스크롤 + 초기/Follow-up 추천 검색어 풍선말.
export default function MessageList({
  messages,
  isStreaming,
  suggested = [],
  followUps = [],
  onSuggested,
  emptyHint,
  suggestedLabel,
  followUpLabel,
}: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isStreaming]);

  const lastIsAssistantComplete =
    messages.length > 0 &&
    messages[messages.length - 1].role === "assistant" &&
    !isStreaming &&
    Boolean(messages[messages.length - 1].text);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
      {messages.length === 0 && (
        <div className="flex flex-col items-center justify-center gap-3 text-gray-500 text-sm text-center pt-6">
          <div>{emptyHint ?? "질문을 입력하세요."}</div>
          {suggested.length > 0 && (
            <div className="flex flex-col items-center gap-2 max-w-md">
              <div className="text-[10px] uppercase tracking-wider text-gray-600">
                {suggestedLabel ?? "추천 검색어"}
              </div>
              <div className="flex flex-wrap gap-2 justify-center">
                {suggested.map((q) => (
                  <button
                    key={q}
                    type="button"
                    onClick={() => onSuggested?.(q)}
                    disabled={isStreaming}
                    className="px-3 py-1.5 text-xs rounded-full bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white border border-gray-700 transition-colors disabled:opacity-50"
                  >
                    💬 {q}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
      {messages.map((m) => (
        <div
          key={m.id}
          className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
        >
          <div
            className={`max-w-[85%] rounded-lg px-3 py-2 ${
              m.role === "user"
                ? "bg-blue-600 text-white"
                : "bg-gray-800 text-gray-100 border border-gray-700"
            }`}
          >
            {m.role === "user" ? (
              <p className="text-sm whitespace-pre-wrap break-words">{m.text}</p>
            ) : (
              <>
                {m.text ? (
                  <MessageMarkdown text={m.text} />
                ) : isStreaming ? (
                  <span className="inline-flex gap-1 items-center text-gray-400 text-xs">
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-500 animate-pulse" />
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-500 animate-pulse [animation-delay:200ms]" />
                    <span className="w-1.5 h-1.5 rounded-full bg-gray-500 animate-pulse [animation-delay:400ms]" />
                  </span>
                ) : null}
                {m.toolCalls && m.toolCalls.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {m.toolCalls.map((tc, i) => (
                      <span
                        key={i}
                        className="text-[10px] uppercase tracking-wider bg-purple-500/20 text-purple-300 border border-purple-500/30 px-1.5 py-0.5 rounded"
                      >
                        🛠 {tc.name}
                      </span>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      ))}

      {lastIsAssistantComplete && followUps.length > 0 && (
        <div className="flex flex-col gap-2 pt-1">
          <div className="text-[10px] uppercase tracking-wider text-gray-500 pl-1">
            {followUpLabel ?? "이어서 물어보기"}
          </div>
          <div className="flex flex-wrap gap-2">
            {followUps.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => onSuggested?.(q)}
                disabled={isStreaming}
                className="px-2.5 py-1 text-[11px] rounded-full bg-gray-800/70 hover:bg-gray-700 text-gray-300 hover:text-white border border-gray-700 transition-colors disabled:opacity-50"
              >
                ↪ {q}
              </button>
            ))}
          </div>
        </div>
      )}

      <div ref={bottomRef} />
    </div>
  );
}
