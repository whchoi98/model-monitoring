"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AuthUser } from "@/lib/types";
import { fetchMe, getToken, setToken } from "@/lib/api";
import { useT, useLang, LanguageProvider } from "@/lib/i18n-context";
import LoginForm from "@/components/LoginForm";
import FloatingChat from "@/components/chat/FloatingChat";
import PromptsPanel from "@/components/PromptsPanel";
import { APP_VERSION } from "@/lib/version";
import AppHeader, { useNavItems } from "@/components/AppHeader";
import ThemeToggle from "@/components/ThemeToggle";

export default function PromptsPage() {
  return (
    <LanguageProvider>
      <PromptsPageContent />
    </LanguageProvider>
  );
}

function PromptsPageContent() {
  const t = useT();
  const { lang, setLang } = useLang();

  const navItems = useNavItems("prompts");
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginModalOpen, setLoginModalOpen] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (token) {
      fetchMe()
        .then(setUser)
        .catch(() => setToken(null))
        .finally(() => setAuthChecked(true));
    } else {
      setAuthChecked(true);
    }
  }, []);

  const handleLoginSuccess = (username: string) => {
    setUser({ id: 0, username });
    fetchMe().then(setUser).catch(() => {});
    setLoginModalOpen(false);
  };

  const handleLogout = () => {
    setToken(null);
    setUser(null);
  };

  if (!authChecked) {
    return null;
  }

  return (
    <div className="min-h-screen">
      {/* Header - 메인 페이지와 동일 구조, Prompts 탭만 활성화 */}
      <AppHeader items={navItems} user={user} onLoginClick={() => setLoginModalOpen(true)} onLogout={handleLogout} />

      {/* 미인증 사용자는 페이지 접근 불가 — LoginForm 또는 안내만 표시. */}
      {user ? (
        <PromptsPanel user={user} onLoginClick={() => setLoginModalOpen(true)} />
      ) : (
        <div className="p-6 max-w-md mx-auto mt-12">
          <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-6 space-y-4">
            <h2 className="text-lg font-semibold text-gray-100">
              {lang === "en" ? "Login required" : "로그인이 필요합니다"}
            </h2>
            <p className="text-sm text-gray-400">
              {lang === "en"
                ? "Prompts manage prompt sets and Bedrock OptimizePrompt. Sign in to use this page."
                : "프롬프트는 프롬프트 세트 관리와 Bedrock OptimizePrompt를 사용합니다. 로그인 후 사용하세요."}
            </p>
            <LoginForm onLoginSuccess={handleLoginSuccess} />
          </div>
        </div>
      )}

      <FloatingChat />

      {/* Login Modal */}
      {loginModalOpen && !user && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button
            type="button"
            aria-label="overlay"
            onClick={() => setLoginModalOpen(false)}
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
          />
          <div className="relative w-full max-w-md bg-gray-900 border border-gray-800 rounded-xl shadow-2xl p-6">
            <button
              type="button"
              onClick={() => setLoginModalOpen(false)}
              className="absolute top-3 right-3 text-gray-400 hover:text-white text-xl leading-none"
              aria-label="close"
            >
              ×
            </button>
            <LoginForm onLoginSuccess={handleLoginSuccess} />
          </div>
        </div>
      )}
    </div>
  );
}
