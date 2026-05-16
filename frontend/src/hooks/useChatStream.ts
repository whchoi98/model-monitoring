"use client";

import { useCallback, useRef, useState } from "react";
import { ChatMessage } from "@/lib/types";
import { chatStream } from "@/lib/api";

// SSE 스트리밍 채팅 상태 훅.
// - send(message): 사용자 메시지를 큐에 추가하고 backend SSE 호출.
// - delta 이벤트를 받아 마지막 assistant 메시지에 누적.
// - final 이벤트로 정확히 1회 종료.
export function useChatStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const send = useCallback(
    (text: string) => {
      const trimmed = text.trim();
      if (!trimmed || isStreaming) return;

      setError(null);

      const userMsg: ChatMessage = {
        id: `u-${Date.now()}`,
        role: "user",
        text: trimmed,
      };
      const assistantMsg: ChatMessage = {
        id: `a-${Date.now()}`,
        role: "assistant",
        text: "",
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      setIsStreaming(true);

      const updateAssistant = (mutator: (m: ChatMessage) => ChatMessage) =>
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (!last || last.role !== "assistant") return prev;
          return [...prev.slice(0, -1), mutator(last)];
        });

      const ctrl = chatStream(
        { message: trimmed, session_id: sessionId },
        {
          onDelta: (delta) => updateAssistant((m) => ({ ...m, text: m.text + delta })),
          onToolCall: (call) =>
            updateAssistant((m) => ({
              ...m,
              toolCalls: [...(m.toolCalls ?? []), { name: call.name, input: call.input }],
            })),
          onWarning: (msg) => setError(`warning: ${msg}`),
          onFinal: (payload) => {
            setIsStreaming(false);
            if (payload.session_id) setSessionId(payload.session_id);
            if (!payload.ok && payload.error) setError(payload.error);
          },
          onError: (err) => {
            setError(err.message);
            setIsStreaming(false);
          },
        },
      );
      controllerRef.current = ctrl;
    },
    [isStreaming, sessionId],
  );

  const cancel = useCallback(() => {
    controllerRef.current?.abort();
    setIsStreaming(false);
  }, []);

  const reset = useCallback(() => {
    cancel();
    setMessages([]);
    setError(null);
    setSessionId(null);
  }, [cancel]);

  return { messages, isStreaming, error, sessionId, send, cancel, reset };
}
