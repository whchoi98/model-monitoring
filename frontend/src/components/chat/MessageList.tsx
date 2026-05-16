"use client";

import { useEffect, useRef } from "react";
import { ChatMessage } from "@/lib/types";
import MessageMarkdown from "./MessageMarkdown";

interface MessageListProps {
  messages: ChatMessage[];
  isStreaming: boolean;
}

// 메시지 리스트 — 자동으로 마지막 메시지로 스크롤.
export default function MessageList({ messages, isStreaming }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, isStreaming]);

  return (
    <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
      {messages.length === 0 && (
        <div className="h-full flex items-center justify-center text-gray-500 text-sm text-center">
          질문을 입력하세요.<br />
          (예: &quot;Sonnet 4.5와 Haiku 4.5 최근 6시간 TPS 비교&quot;)
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
      <div ref={bottomRef} />
    </div>
  );
}
