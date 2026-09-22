"use client";

import { useLang } from "@/lib/i18n-context";
import { useAuth } from "@/lib/auth-context";
import AppShell from "@/components/AppShell";
import PromptsPanel from "@/components/PromptsPanel";

export const dynamic = "force-dynamic";

export default function PromptsPage() {
  const { lang } = useLang();
  const { user, checking, openLogin } = useAuth();

  return (
    <AppShell navKey="prompts">
      {user ? (
        <PromptsPanel user={user} onLoginClick={() => openLogin()} />
      ) : (
        <div className="mx-auto mt-12 max-w-md p-6">
          <div className="space-y-4 rounded-xl border border-gray-800 bg-gray-900/50 p-6">
            <h1 className="text-lg font-semibold text-gray-100">
              {lang === "en" ? "Prompts" : "프롬프트"}
            </h1>
            <p role={checking ? "status" : undefined} className="text-sm text-gray-400">
              {checking
                ? (lang === "en" ? "Checking sign-in…" : "로그인 상태 확인 중…")
                : (lang === "en"
                  ? "Sign in to manage prompt sets and use Bedrock OptimizePrompt."
                  : "프롬프트 세트 관리와 Bedrock OptimizePrompt는 로그인 후 이용할 수 있습니다.")}
            </p>
            <button type="button" onClick={() => openLogin()} disabled={checking}
              className="min-h-10 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white disabled:opacity-50">
              {lang === "en" ? "Login" : "로그인"}
            </button>
          </div>
        </div>
      )}
    </AppShell>
  );
}
