"use client";

import { KeyboardEvent, useState } from "react";

interface ChatInputProps {
  disabled?: boolean;
  onSubmit: (text: string) => void;
  onCancel?: () => void;
  isStreaming?: boolean;
}

// 입력 박스 — Enter 전송, Shift+Enter 줄바꿈.
export default function ChatInput({ disabled, onSubmit, onCancel, isStreaming }: ChatInputProps) {
  const [value, setValue] = useState("");

  const submit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setValue("");
  };

  const handleKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div className="border-t border-gray-800 px-3 py-2 bg-gray-900">
      <div className="flex items-end gap-2">
        <textarea
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKey}
          disabled={disabled}
          rows={1}
          placeholder={isStreaming ? "응답 생성 중..." : "메시지 입력 (Enter 전송, Shift+Enter 줄바꿈)"}
          className="flex-1 bg-gray-950 border border-gray-700 rounded-md px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500 resize-none max-h-32"
        />
        {isStreaming && onCancel ? (
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-2 rounded-md text-xs font-medium bg-red-600 hover:bg-red-500 text-white"
          >
            중단
          </button>
        ) : (
          <button
            type="button"
            onClick={submit}
            disabled={disabled || !value.trim()}
            className="px-3 py-2 rounded-md text-xs font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 disabled:cursor-not-allowed"
          >
            전송
          </button>
        )}
      </div>
    </div>
  );
}
