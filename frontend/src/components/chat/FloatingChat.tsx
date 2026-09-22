"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useUaPopupStrategy } from "@/hooks/useUaPopupStrategy";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n-context";
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
  const { user, checking, openLogin } = useAuth();
  const { lang } = useLang();
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

  const showChat = useCallback(() => {
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

  const handleClick = () => {
    if (checking) return;
    if (!user) {
      openLogin(showChat);
      return;
    }
    showChat();
  };

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        disabled={checking}
        className="fixed bottom-24 right-6 z-40 w-16 h-16 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 hover:from-blue-400 hover:to-indigo-500 text-white shadow-2xl border-2 border-blue-300/50 flex items-center justify-center transition-transform hover:scale-110"
        aria-label={lang === "en" ? "Open chatbot" : "챗봇 열기"}
        title={lang === "en" ? "Open Bedrock Monitor chatbot" : "Bedrock Monitor 챗봇 열기"}
      >
        {/* 챗봇 느낌 - 헤드셋/안테나가 있는 친근한 로봇 얼굴 */}
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.8}
          strokeLinecap="round"
          strokeLinejoin="round"
          className="w-8 h-8"
        >
          {/* 안테나 */}
          <line x1="12" y1="3" x2="12" y2="5" />
          <circle cx="12" cy="2.5" r="0.8" fill="currentColor" />
          {/* 머리 본체 */}
          <rect x="4" y="6" width="16" height="13" rx="3" />
          {/* 두 눈 */}
          <circle cx="9" cy="12" r="1.2" fill="currentColor" />
          <circle cx="15" cy="12" r="1.2" fill="currentColor" />
          {/* 입(미소) */}
          <path d="M9 16 Q12 17.5 15 16" />
          {/* 양 귀(헤드폰 느낌) */}
          <line x1="3" y1="11" x2="3" y2="14" />
          <line x1="21" y1="11" x2="21" y2="14" />
        </svg>
      </button>
      <ChatModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
