"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AuthUser } from "@/lib/types";
import { fetchMe, getToken, setToken } from "@/lib/api";
import { useT, useLang, LanguageProvider } from "@/lib/i18n-context";
import LoginForm from "@/components/LoginForm";
import FloatingChat from "@/components/chat/FloatingChat";
import ReliabilityPanel from "@/components/ReliabilityPanel";
import { APP_VERSION } from "@/lib/version";
import ThemeToggle from "@/components/ThemeToggle";

export default function ReliabilityPage() {
  return (
    <LanguageProvider>
      <Inner />
    </LanguageProvider>
  );
}

function Inner() {
  const t = useT();
  const { lang, setLang } = useLang();
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginModalOpen, setLoginModalOpen] = useState(false);

  useEffect(() => {
    const token = getToken();
    if (token) {
      fetchMe().then(setUser).catch(() => setToken(null)).finally(() => setAuthChecked(true));
    } else {
      setAuthChecked(true);
    }
  }, []);

  const handleLoginSuccess = (username: string) => {
    setUser({ id: 0, username });
    fetchMe().then(setUser).catch(() => {});
    setLoginModalOpen(false);
  };
  const handleLogout = () => { setToken(null); setUser(null); };

  if (!authChecked) return null;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-40 bg-gray-950/90 backdrop-blur border-b border-gray-800">
        <div className="flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-100">{t.appTitle}</h1>
              <p className="text-xs text-gray-500">{t.appDesc}</p>
              <span className="text-[10px] text-gray-600 font-mono tabular-nums">{APP_VERSION}</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex bg-gray-800/50 rounded-lg p-0.5">
              <button onClick={() => setLang("ko")} className={`px-2 py-1 text-xs font-medium rounded-md ${lang === "ko" ? "bg-gray-600 text-white" : "text-gray-400 hover:text-gray-200"}`}>KO</button>
              <button onClick={() => setLang("en")} className={`px-2 py-1 text-xs font-medium rounded-md ${lang === "en" ? "bg-gray-600 text-white" : "text-gray-400 hover:text-gray-200"}`}>EN</button>
              <ThemeToggle />
            </div>
            <nav className="flex bg-gray-800/50 rounded-lg p-0.5">
              <Link href="/" className="px-4 py-1.5 text-sm font-medium rounded-md text-gray-400 hover:text-gray-200">{t.dashboardTab}</Link>
              <Link href="/" className="px-4 py-1.5 text-sm font-medium rounded-md text-gray-400 hover:text-gray-200">{t.manualProbeTab}</Link>
              <Link href="/prompts" className="px-4 py-1.5 text-sm font-medium rounded-md text-gray-400 hover:text-gray-200">{lang === "en" ? "Prompts" : "프롬프트"}</Link>
              <Link href="/cost" className="px-4 py-1.5 text-sm font-medium rounded-md text-gray-400 hover:text-gray-200">{lang === "en" ? "Cost" : "비용"}</Link>
              <span className="px-4 py-1.5 text-sm font-medium rounded-md bg-blue-600 text-white">{lang === "en" ? "Reliability" : "신뢰성"}</span>
              <Link href="/efficiency" className="px-4 py-1.5 text-sm font-medium rounded-md text-gray-400 hover:text-gray-200">{lang === "en" ? "Efficiency" : "효율성"}</Link>
              <Link href="/analysis" className="px-4 py-1.5 text-sm font-medium rounded-md text-gray-400 hover:text-gray-200">{lang === "en" ? "Analysis" : "분석"}</Link>
            </nav>
            {user ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">{user.username}</span>
                <button onClick={handleLogout} className="px-3 py-1.5 text-xs font-medium text-gray-400 hover:text-gray-200 bg-gray-800 hover:bg-gray-700 rounded-lg">{t.logout}</button>
              </div>
            ) : (
              <button onClick={() => setLoginModalOpen(true)} className="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg">{lang === "en" ? "Login" : "로그인"}</button>
            )}
          </div>
        </div>
      </header>

      <ReliabilityPanel />

      <FloatingChat />

      {loginModalOpen && !user && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <button type="button" aria-label="overlay" onClick={() => setLoginModalOpen(false)} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
          <div className="relative w-full max-w-md bg-gray-900 border border-gray-800 rounded-xl shadow-2xl p-6">
            <button type="button" onClick={() => setLoginModalOpen(false)} className="absolute top-3 right-3 text-gray-400 hover:text-white text-xl leading-none" aria-label="close">×</button>
            <LoginForm onLoginSuccess={handleLoginSuccess} />
          </div>
        </div>
      )}
    </div>
  );
}
