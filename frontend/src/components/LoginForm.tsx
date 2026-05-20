"use client";

import { useState } from "react";
import { useT } from "@/lib/i18n-context";
import { login, register, setToken } from "@/lib/api";

interface Props {
  onLoginSuccess: (username: string) => void;
}

export default function LoginForm({ onLoginSuccess }: Props) {
  const t = useT();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setLoading(true);

    try {
      if (mode === "login") {
        const res = await login(username, password);
        setToken(res.access_token);
        onLoginSuccess(res.username);
      } else {
        await register(username, password);
        setSuccess(t.registerSuccess);
        setMode("login");
        setPassword("");
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "";
      // Detect pending approval error from backend
      if (msg.includes("승인 대기") || msg.includes("승인")) {
        setError(t.pendingApproval);
      } else {
        setError(msg || (mode === "login" ? t.loginError : t.registerError));
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex items-center justify-center py-24">
      <div className="w-full max-w-sm">
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-6">
          {/* Header */}
          <div className="text-center mb-6">
            <div className="w-12 h-12 bg-blue-600/10 border border-blue-500/20 rounded-xl flex items-center justify-center mx-auto mb-3">
              <svg className="w-6 h-6 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
              </svg>
            </div>
            <h2 className="text-lg font-semibold text-gray-100">
              {mode === "login" ? t.loginTitle : t.registerButton}
            </h2>
            <p className="text-xs text-gray-500 mt-1">{t.loginDesc}</p>
          </div>

          {/* Messages */}
          {error && (
            <div className="mb-4 p-3 rounded-lg bg-rose-500/10 border border-rose-500/20 text-xs text-rose-400">
              {error}
            </div>
          )}
          {success && (
            <div className="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-300">
              <div className="flex items-start gap-2">
                <svg className="w-4 h-4 flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span>{success}</span>
              </div>
            </div>
          )}

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">
                {mode === "register" ? "이메일 (아이디)" : t.username}
              </label>
              <input
                type={mode === "register" ? "email" : "text"}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
                minLength={2}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                placeholder={mode === "register" ? "you@example.com" : "admin"}
                autoComplete={mode === "register" ? "email" : "username"}
              />
              {mode === "register" && (
                <p className="mt-1 text-[11px] text-gray-500">
                  관리자 승인 알림 발송을 위해 이메일 형식으로 입력하세요.
                </p>
              )}
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-400 mb-1.5">{t.password}</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={4}
                className="w-full px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                placeholder="••••••••"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "..." : mode === "login" ? t.loginButton : t.registerButton}
            </button>
          </form>

          {/* Toggle */}
          <div className="mt-4 text-center">
            <button
              onClick={() => { setMode(mode === "login" ? "register" : "login"); setError(null); setSuccess(null); }}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
            >
              {mode === "login" ? t.noAccount : t.hasAccount}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
