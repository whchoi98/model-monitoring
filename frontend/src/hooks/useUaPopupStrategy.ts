"use client";

// 챗봇 표시 모드 분기 — Chrome iframe modal / Firefox popup window.
//
// 동작:
//   - Firefox 계열 UA: window.open('popup=yes,...') 시도. 성공하면 'popup'.
//   - 그 외 (Chrome 등): Site Engagement Score에 따라 popup이 새 탭으로 열릴 수
//     있어 iframe modal로 강제.
//   - popup 시도가 차단되거나 실패하면 'iframe' fallback.
//
// 본 훅은 트리거 시점에 호출되는 함수만 노출 (자동 모드 결정 X).

export type PopupMode = "popup" | "iframe";

const POPUP_FEATURES = "popup=yes,width=420,height=640,resizable=yes,scrollbars=yes";

export function useUaPopupStrategy() {
  // 동기 함수: 사용자 클릭 핸들러 내부에서 호출되어야 popup 차단을 회피.
  const openChat = (url: string): { mode: PopupMode; popup: Window | null } => {
    if (typeof window === "undefined") {
      return { mode: "iframe", popup: null };
    }

    const isFirefox = /Firefox/i.test(navigator.userAgent);
    const isSafari =
      /^((?!chrome|android).)*safari/i.test(navigator.userAgent) && !isFirefox;

    if (isFirefox || isSafari) {
      // popup이 새 창으로 안정적으로 열리는 브라우저.
      const popup = window.open(url, "bedrock-monitor-chat", POPUP_FEATURES);
      if (popup && !popup.closed) {
        return { mode: "popup", popup };
      }
    }

    // Chrome 등 — popup 차단/새 탭 변환 가능성. iframe modal로 fallback.
    return { mode: "iframe", popup: null };
  };

  return { openChat };
}
