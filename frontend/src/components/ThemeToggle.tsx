"use client";

import { setTheme, useTheme } from "@/lib/theme";
import { useLang } from "@/lib/i18n-context";

/** 다크/화이트 테마 토글 — 각 페이지 헤더의 KO/EN 토글 옆에 배치. */
export default function ThemeToggle() {
  const theme = useTheme();
  const { lang } = useLang();
  const isLight = theme === "light";
  const label = lang === "en"
    ? (isLight ? "Switch to dark theme" : "Switch to light theme")
    : (isLight ? "다크 테마로 전환" : "라이트 테마로 전환");

  return (
    <button
      type="button"
      onClick={() => setTheme(isLight ? "dark" : "light")}
      className="min-h-9 min-w-9 px-2 py-1 text-xs font-medium rounded-md text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 transition-colors"
      title={label}
      aria-label={label}
      aria-pressed={isLight}
    >
      <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
        {isLight ? <path d="M20.5 14.4A8.5 8.5 0 019.6 3.5 8.5 8.5 0 1020.5 14.4Z" /> : <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>}
      </svg>
    </button>
  );
}
