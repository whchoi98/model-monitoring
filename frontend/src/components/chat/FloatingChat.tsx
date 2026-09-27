"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useChatFabVisibility } from "@/hooks/useChatFabVisibility";
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
//
// 스크롤 시 숨김 (v2.31.1, 사용자 결정): 버튼이 표 글자를 가리지 않도록 창을 아래로 스크롤하거나 표를 가로로
// 스크롤하면 아래로 미끄러지며 사라지고, 위로 스크롤, 맨 위, 맨 아래, 포커스, 챗봇 창 열림이면 돌아온다
// (규칙은 lib/fabVisibility.ts, 이벤트는 hooks/useChatFabVisibility.ts). 숨긴 상태도 DOM과 탭 순서에 남아
// 키보드 포커스가 닿으면 보인다(aria-hidden, tabIndex를 바꾸지 않는다). AppShell <main>의 아래 여백(pb-24 sm:pb-28)이
// 버튼 높이 + 아래 간격 + 1rem보다 커서 페이지 끝 내용은 보이는 버튼 아래에 놓이지 않는다.
const FAB_CLASS =
  "fixed right-4 bottom-[calc(1rem_+_env(safe-area-inset-bottom))] sm:right-6 sm:bottom-[calc(1.5rem_+_env(safe-area-inset-bottom))] "
  + "z-40 w-12 h-12 sm:w-16 sm:h-16 rounded-full bg-gradient-to-br from-blue-500 to-indigo-600 hover:from-blue-400 hover:to-indigo-500 "
  + "text-white shadow-2xl border-2 border-blue-300/50 flex items-center justify-center "
  + "transition-[transform,opacity] duration-200 ease-out motion-reduce:transition-none hover:scale-110";
// Slides below the viewport (its own height + the largest bottom offset) and fades; no pointer hits while hidden.
const FAB_HIDDEN_CLASS = "translate-y-[calc(100%_+_2rem_+_env(safe-area-inset-bottom))] opacity-0 pointer-events-none";

export default function FloatingChat() {
  const { openChat } = useUaPopupStrategy();
  const [modalOpen, setModalOpen] = useState(false);
  const { user, checking, openLogin } = useAuth();
  const { lang } = useLang();
  const popupRef = useRef<Window | null>(null);
  const fab = useChatFabVisibility(modalOpen);

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
        onFocus={fab.onFocus}
        onBlur={fab.onBlur}
        disabled={checking}
        data-chat-fab
        data-visible={fab.visible ? "true" : "false"}
        className={fab.visible ? FAB_CLASS : `${FAB_CLASS} ${FAB_HIDDEN_CLASS}`}
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
          className="w-6 h-6 sm:w-8 sm:h-8"
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
