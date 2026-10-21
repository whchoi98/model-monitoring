"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChatMessage } from "@/lib/types";
import { chatStream, getToken } from "@/lib/api";

export function useChatStream() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [followups, setFollowups] = useState<string[]>([]);
  const controller = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const busy = useRef(false);

  const cancel = useCallback(() => {
    generation.current++;
    controller.current?.abort();
    controller.current = null;
    busy.current = false;
    setIsStreaming(false);
  }, []);
  const reset = useCallback(() => {
    cancel();
    setMessages([]);
    setError(null);
    setSessionId(null);
    setFollowups([]);
  }, [cancel]);

  useEffect(() => {
    let token = getToken();
    const identityChanged = () => {
      const next = getToken();
      if (next !== token) { token = next; reset(); }
    };
    window.addEventListener("auth-changed", identityChanged);
    return () => {
      window.removeEventListener("auth-changed", identityChanged);
      generation.current++;
      controller.current?.abort();
    };
  }, [reset]);

  const send = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || busy.current) return;
    busy.current = true;
    const current = ++generation.current;
    const active = () => generation.current === current;
    setError(null);
    const id = `${Date.now()}-${current}`;
    setMessages(previous => [...previous,
      { id: `u-${id}`, role: "user", text: trimmed },
      { id: `a-${id}`, role: "assistant", text: "" },
    ]);
    setIsStreaming(true);
    setFollowups([]);
    const updateAssistant = (mutator: (message: ChatMessage) => ChatMessage) => {
      if (!active()) return;
      setMessages(previous => previous.map(message => message.id === `a-${id}` ? mutator(message) : message));
    };
    const finish = () => { busy.current = false; setIsStreaming(false); controller.current = null; };
    controller.current = chatStream({ message: trimmed, session_id: sessionId }, {
      onDelta: delta => updateAssistant(message => ({ ...message, text: message.text + delta })),
      onToolCall: call => updateAssistant(message => ({
        ...message, toolCalls: [...(message.toolCalls ?? []), { name: call.name, input: call.input }],
      })),
      onWarning: message => { if (active()) setError(message); },
      onFollowups: suggestions => { if (active()) setFollowups(suggestions); },
      onFinal: payload => {
        if (!active()) return;
        finish();
        if (payload.session_id) setSessionId(payload.session_id);
        if (!payload.ok) setError(payload.error || "The analysis could not be completed.");
      },
      onError: cause => {
        if (!active()) return;
        setError(cause.message);
        finish();
      },
    });
  }, [sessionId]);

  return { messages, isStreaming, error, sessionId, followups, send, cancel, reset };
}
