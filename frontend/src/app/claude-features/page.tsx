"use client";

export const dynamic = "force-dynamic";

import { useEffect, useState } from "react";
import { AuthUser } from "@/lib/types";
import { fetchMe, getToken, setToken } from "@/lib/api";
import { LanguageProvider } from "@/lib/i18n-context";
import LoginForm from "@/components/LoginForm";
import FloatingChat from "@/components/chat/FloatingChat";
import ClaudeFeaturesPanel from "@/components/ClaudeFeaturesPanel";
import AppHeader, { useNavItems } from "@/components/AppHeader";

export default function ClaudeFeaturesPage() {
  return (
    <LanguageProvider>
      <Inner />
    </LanguageProvider>
  );
}

function Inner() {
  const navItems = useNavItems("features");
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
      <AppHeader items={navItems} user={user} onLoginClick={() => setLoginModalOpen(true)} onLogout={handleLogout} />
      <ClaudeFeaturesPanel />
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
