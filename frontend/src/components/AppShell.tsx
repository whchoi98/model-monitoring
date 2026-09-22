"use client";

import type { ReactNode } from "react";
import { usePageTitle } from "@/hooks/usePageTitle";
import { useAuth } from "@/lib/auth-context";
import { useLang } from "@/lib/i18n-context";
import AppHeader, { useNavItems } from "./AppHeader";
import FloatingChat from "./chat/FloatingChat";

export default function AppShell({
  children, navKey, actions,
}: {
  children: ReactNode;
  navKey: string;
  actions?: ReactNode;
}) {
  const { lang } = useLang();
  const { user, checking, openLogin, logout, error, retry } = useAuth();
  const items = useNavItems(navKey);
  const activeLabel = items.find((item) => item.active)?.label;

  usePageTitle(activeLabel ? `${activeLabel} | LLM Monitor` : "LLM Monitor");

  return (
    <div className="min-h-screen min-w-0">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-2 focus:z-50 focus:rounded-lg focus:bg-blue-600 focus:px-4 focus:py-3 focus:text-white"
      >
        {lang === "en" ? "Skip to content" : "본문으로 바로가기"}
      </a>
      <AppHeader
        items={items} user={user} checking={checking}
        onLoginClick={openLogin} onLogout={logout} actions={actions}
      />
      {error && (
        <div role="status" className="flex flex-wrap items-center gap-3 border-b border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-300 sm:px-6">
          <span>
            {lang === "en"
              ? error === "storage"
                ? "Sign-in storage is unavailable in this browser. Public monitoring is still available."
                : "Unable to check your sign-in right now. Public monitoring is still available."
              : error === "storage"
                ? "브라우저의 로그인 저장소를 사용할 수 없습니다. 공개 모니터링은 계속 이용할 수 있습니다."
                : "지금은 로그인 상태를 확인할 수 없습니다. 공개 모니터링은 계속 이용할 수 있습니다."}
          </span>
          <button
            type="button" onClick={retry} disabled={checking}
            aria-label={lang === "en" ? "Retry sign-in check" : "로그인 상태 다시 확인"}
            className="min-h-9 rounded-md border border-amber-500/30 px-3 font-medium disabled:opacity-50"
          >
            {lang === "en" ? "Retry" : "다시 시도"}
          </button>
        </div>
      )}
      <main id="main-content" tabIndex={-1} className="min-w-0">{children}</main>
      <FloatingChat />
    </div>
  );
}
