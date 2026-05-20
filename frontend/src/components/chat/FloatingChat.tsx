"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useUaPopupStrategy } from "@/hooks/useUaPopupStrategy";
import { fetchMe, getToken } from "@/lib/api";
import LoginForm from "../LoginForm";
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
  const [loginOpen, setLoginOpen] = useState(false);
  const [authed, setAuthed] = useState(false);
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

  // 인증 상태 확인. 토큰 없으면 로그인 모달부터.
  const refreshAuth = useCallback(() => {
    if (!getToken()) {
      setAuthed(false);
      return;
    }
    fetchMe().then(() => setAuthed(true)).catch(() => setAuthed(false));
  }, []);

  useEffect(() => {
    refreshAuth();
  }, [refreshAuth]);

  const handleClick = useCallback(() => {
    if (!authed) {
      setLoginOpen(true);
      return;
    }
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
  }, [authed, openChat]);

  const handleLoginSuccess = () => {
    setLoginOpen(false);
    refreshAuth();
    // 로그인 직후 챗봇 자동 오픈.
    setTimeout(() => {
      const result = openChat("/chat");
      if (result.mode === "popup" && result.popup) {
        popupRef.current = result.popup;
      } else {
        setModalOpen(true);
      }
    }, 100);
  };

  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        className="fixed bottom-24 right-6 z-40 w-16 h-16 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 hover:from-blue-400 hover:to-indigo-500 text-white shadow-2xl border-2 border-blue-300/50 flex items-center justify-center transition-transform hover:scale-110"
        aria-label="open chatbot"
        title="Bedrock Monitor 챗봇 열기"
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
      {loginOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            aria-label="overlay"
            onClick={() => setLoginOpen(false)}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          <div className="relative w-full max-w-md bg-gray-900 border border-gray-800 rounded-xl shadow-2xl p-6">
            <button
              type="button"
              onClick={() => setLoginOpen(false)}
              className="absolute top-3 right-3 text-gray-400 hover:text-white text-xl leading-none"
              aria-label="close"
            >
              ×
            </button>
            <LoginForm onLoginSuccess={handleLoginSuccess} />
          </div>
        </div>
      )}
    </>
  );
}
