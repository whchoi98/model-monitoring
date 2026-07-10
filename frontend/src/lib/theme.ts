// 다크/화이트 테마 상태 (v2.8.0).
//
// 방식: Tailwind gray 스케일이 CSS 변수(rgb triplet)로 재매핑되어 있어(globals.css /
// tailwind.config.ts), <html>에 .light 클래스를 붙이는 것만으로 전체 앱이 전환된다 —
// 기존 컴포넌트의 bg-gray-* 클래스 495곳을 수정하지 않는 설계.
// 기본 다크. 선택은 localStorage('theme')에 저장, layout.tsx의 인라인 스크립트가
// 하이드레이션 전에 복원해 FOUC를 방지한다.
"use client";

import { useSyncExternalStore } from "react";

export type Theme = "dark" | "light";

const STORAGE_KEY = "theme";
const EVENT = "themechange";

export function getTheme(): Theme {
  if (typeof document === "undefined") return "dark";
  return document.documentElement.classList.contains("light") ? "light" : "dark";
}

export function setTheme(theme: Theme): void {
  document.documentElement.classList.toggle("light", theme === "light");
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* storage 차단 환경에서도 세션 내 전환은 동작 */
  }
  window.dispatchEvent(new CustomEvent(EVENT));
}

function subscribe(callback: () => void): () => void {
  window.addEventListener(EVENT, callback);
  return () => window.removeEventListener(EVENT, callback);
}

/** 현재 테마를 반응형으로 구독 (차트 색상 분기 등). SSR 스냅샷은 다크. */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, getTheme, () => "dark");
}
