"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useUaPopupStrategy } from "@/hooks/useUaPopupStrategy";
import ChatModal from "./ChatModal";

// 우하단 플로팅 버튼 + iframe modal / popup window 듀얼 모드.
//
// Firefox: window.open로 popup window 열기 (대화 컨텍스트는 같은 origin이라
//   localStorage로 token 공유 — Next.js dev에서도 동작).
// Chrome 등: ChatModal (overlay)로 페널 노출.
// 팝업 차단 시 → 자동으로 modal fallback.
export default function FloatingChat() {
  const { openChat } = useUaPopupStrategy();
  const [modalOpen, setModalOpen] = useState(false);
  const popupRef = useRef<Window | null>(null);

  // popup 창이 사용자에 의해 닫혔는지 1초마다 확인 — 닫혔으면 ref 정리.
  useEffect(() => {
    if (!popupRef.current) return;
    const id = setInterval(() => {
      if (popupRef.current?.closed) {
        popupRef.current = null;
        clearInterval(id);
      }
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const handleClick = useCallback(() => {
    // popup 이미 열려있으면 focus.
    if (popupRef.current && !popupRef.current.closed) {
      popupRef.current.focus();
      return;
    }

    const result = openChat("/chat");
    if (result.mode === "popup" && result.popup) {
      popupRef.current = result.popup;
    } else {
      setModalOpen(true);
    }
  }, [openChat]);

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        className="fixed bottom-6 right-6 z-40 w-14 h-14 rounded-full bg-blue-600 hover:bg-blue-500 text-white shadow-2xl border border-blue-400/40 flex items-center justify-center transition-transform hover:scale-105"
        aria-label="open chatbot"
        title="Bedrock Monitor 챗봇 열기"
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="w-6 h-6"
        >
          <path d="M21 12c0 4-4 7-9 7-1.5 0-3-.3-4.3-.8L3 20l1.5-3.7C3.5 15.3 3 13.7 3 12c0-4 4-7 9-7s9 3 9 7z" />
        </svg>
      </button>
      <ChatModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
