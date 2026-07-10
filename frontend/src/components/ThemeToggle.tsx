"use client";

import { setTheme, useTheme } from "@/lib/theme";

/** 다크/화이트 테마 토글 — 각 페이지 헤더의 KO/EN 토글 옆에 배치. */
export default function ThemeToggle() {
  const theme = useTheme();
  const isLight = theme === "light";

  return (
    <button
      onClick={() => setTheme(isLight ? "dark" : "light")}
      className="px-2 py-1 text-xs font-medium rounded-md text-gray-400 hover:text-gray-200 hover:bg-gray-700/50 transition-colors"
      title={isLight ? "다크 테마로 전환" : "화이트 테마로 전환"}
      aria-label="테마 전환"
    >
      {isLight ? "🌙" : "☀️"}
    </button>
  );
}
