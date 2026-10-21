"use client";

import { KeyboardEvent, useState } from "react";
import { useLang } from "@/lib/i18n-context";

interface ChatInputProps {
  disabled?: boolean;
  onSubmit: (text: string) => void;
  onCancel?: () => void;
  isStreaming?: boolean;
}

// 입력 박스 — Enter 전송, Shift+Enter 줄바꿈.
export default function ChatInput({ disabled, onSubmit, onCancel, isStreaming }: ChatInputProps) {
  const { lang } = useLang();
  const [value, setValue] = useState("");

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setValue("");
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.nativeEvent.isComposing || e.nativeEvent.keyCode === 229) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-gray-800 p-4 bg-gray-900">
      <div className="flex items-end gap-2">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKey}
          disabled={disabled}
          rows={1}
          aria-label={lang === "en" ? "Message" : "메시지"}
          placeholder={isStreaming ? (lang === "en" ? "Generating response…" : "응답 생성 중…") : (lang === "en" ? "Message (Enter to send, Shift+Enter for a new line)" : "메시지 입력 (Enter 전송, Shift+Enter 줄바꿈)")}
          className="ui-input min-w-0 flex-1 resize-none max-h-32 text-gray-100"
        />
        {isStreaming && onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            className="ui-button shrink-0 border-red-500 bg-red-600 text-white hover:bg-red-500"
          >
            {lang === "en" ? "Stop" : "중단"}
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={disabled || !value.trim()}
            className="ui-button-primary shrink-0"
          >
            {lang === "en" ? "Send" : "전송"}
          </button>
        )}
      </div>
    </div>
  );
}
