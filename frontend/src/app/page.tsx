"use client";

// 정적 캐시 비활성화 - 매 요청마다 dynamic SSR 보장.
// CloudFront/브라우저가 옛 HTML(옛 buildId chunk URL 포함)을 캐시해 매 deploy마다
// chunk 404 + 빈 화면이 반복되는 문제 영구 회피.
// 응답 헤더가 자동으로 `cache-control: no-store, must-revalidate, max-age=0`로 설정됨.
export const dynamic = "force-dynamic";

import { useState, useEffect, useCallback } from "react";
import { ModelInfo, ProbeConfig, PromptSet, AuthUser } from "@/lib/types";
import { fetchModels, fetchPromptSets, fetchMe, setToken, getToken } from "@/lib/api";
import { useT, useLang, LanguageProvider } from "@/lib/i18n-context";
import { useProbeStream } from "@/hooks/useProbeStream";
import ModelSelector from "@/components/ModelSelector";
import ProbeConfigPanel from "@/components/ProbeConfigPanel";
import StreamingView from "@/components/StreamingView";
import ResultsTable from "@/components/ResultsTable";
import StatsCards from "@/components/StatsCards";
import LatencyChart from "@/components/LatencyChart";
import ComparisonView from "@/components/ComparisonView";
import HistoryPanel from "@/components/HistoryPanel";
import ProgressBar from "@/components/ProgressBar";
import AutoDashboard from "@/components/AutoDashboard";
import LoginForm from "@/components/LoginForm";
import FloatingChat from "@/components/chat/FloatingChat";
import Link from "next/link";
import { APP_VERSION } from "@/lib/version";

const DEFAULT_CONFIG: ProbeConfig = {
  model_ids: [],
  prompt: "Explain cloud computing in one paragraph.",
  temperature: 0.1,
  max_tokens: 256,
  concurrency: 1,
  repeat_count: 3,
};

type TopTab = "dashboard" | "manual";

export default function HomePage() {
  return (
    <LanguageProvider>
      <HomeContent />
    </LanguageProvider>
  );
}

function HomeContent() {
  const t = useT();
  const { lang, setLang } = useLang();

  const [topTab, setTopTab] = useState<TopTab>("dashboard");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [promptSets, setPromptSets] = useState<PromptSet[]>([]);
  const [config, setConfig] = useState<ProbeConfig>(DEFAULT_CONFIG);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"results" | "charts" | "compare">(
    "results"
  );

  // Auth state
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [loginModalOpen, setLoginModalOpen] = useState(false);

  const stream = useProbeStream();

  // Check existing token on mount
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

  // Load models on mount
  useEffect(() => {
    fetchModels()
      .then(setModels)
      .catch((err) => console.error("Failed to load models:", err));
  }, []);

  // Load prompt sets
  const loadPromptSets = useCallback(() => {
    fetchPromptSets()
      .then(setPromptSets)
      .catch((err) => console.error("Failed to load prompt sets:", err));
  }, []);

  useEffect(() => {
    loadPromptSets();
  }, [loadPromptSets]);

  const handleRun = () => {
    if (config.model_ids.length === 0 || !config.prompt.trim()) return;
    stream.run(config);
  };

  const handleConfigChange = (newConfig: ProbeConfig) => {
    setConfig(newConfig);
  };

  const handleLoginSuccess = (username: string) => {
    setUser({ id: 0, username });
    // Re-fetch to get the real user object
    fetchMe().then(setUser).catch(() => {});
  };

  const handleLogout = () => {
    setToken(null);
    setUser(null);
  };

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-gray-950/90 backdrop-blur border-b border-gray-800">
        <div className="flex items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
              <svg
                className="w-5 h-5 text-white"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M13 10V3L4 14h7v7l9-11h-7z"
                />
              </svg>
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-100">
                {t.appTitle}
              </h1>
              <p className="text-xs text-gray-500">
                {t.appDesc}
              </p>
              <span className="text-[10px] text-gray-600 font-mono tabular-nums">
                {APP_VERSION}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3">
            {/* Language Selector */}
            <div className="flex bg-gray-800/50 rounded-lg p-0.5">
              <button
                onClick={() => setLang("ko")}
                className={`px-2 py-1 text-xs font-medium rounded-md transition-colors ${
                  lang === "ko"
                    ? "bg-gray-600 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                KO
              </button>
              <button
                onClick={() => setLang("en")}
                className={`px-2 py-1 text-xs font-medium rounded-md transition-colors ${
                  lang === "en"
                    ? "bg-gray-600 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                EN
              </button>
            </div>

            {/* Top Tab Navigation */}
            <nav className="flex bg-gray-800/50 rounded-lg p-0.5">
              <button
                onClick={() => setTopTab("dashboard")}
                className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  topTab === "dashboard"
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                {t.dashboardTab}
              </button>
              <button
                onClick={() => setTopTab("manual")}
                className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  topTab === "manual"
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                {t.manualProbeTab}
              </button>
              <Link
                href="/prompts"
                className="px-4 py-1.5 text-sm font-medium rounded-md transition-colors text-gray-400 hover:text-gray-200"
              >
                {lang === "en" ? "Prompts" : "프롬프트"}
              </Link>
              <Link
                href="/cost"
                className="px-4 py-1.5 text-sm font-medium rounded-md transition-colors text-gray-400 hover:text-gray-200"
              >
                {lang === "en" ? "Cost" : "비용"}
              </Link>
              <Link
                href="/reliability"
                className="px-4 py-1.5 text-sm font-medium rounded-md transition-colors text-gray-400 hover:text-gray-200"
              >
                {lang === "en" ? "Reliability" : "신뢰성"}
              </Link>
              <Link
                href="/efficiency"
                className="px-4 py-1.5 text-sm font-medium rounded-md transition-colors text-gray-400 hover:text-gray-200"
              >
                {lang === "en" ? "Efficiency" : "효율성"}
              </Link>
              <Link
                href="/analysis"
                className="px-4 py-1.5 text-sm font-medium rounded-md transition-colors text-gray-400 hover:text-gray-200"
              >
                {lang === "en" ? "Analysis" : "분석"}
              </Link>
            </nav>

            {/* User info / Login / Logout */}
            {user ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">{user.username}</span>
                <button
                  onClick={handleLogout}
                  className="px-3 py-1.5 text-xs font-medium text-gray-400 hover:text-gray-200 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                >
                  {t.logout}
                </button>
              </div>
            ) : (
              <button
                onClick={() => setLoginModalOpen(true)}
                className="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 hover:bg-blue-500 rounded-lg transition-colors"
              >
                {lang === "en" ? "Login" : "로그인"}
              </button>
            )}

            <button
              onClick={() => setHistoryOpen(true)}
              className="flex items-center gap-2 px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-gray-100 rounded-lg transition-colors text-sm"
            >
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              {t.history}
            </button>
          </div>
        </div>
      </header>

      {/* Dashboard Tab */}
      {topTab === "dashboard" && <AutoDashboard />}

      {/* Manual Probe Tab */}
      {topTab === "manual" && !user && authChecked && (
        <LoginForm onLoginSuccess={handleLoginSuccess} />
      )}

      {topTab === "manual" && user && (
        <div className="flex">
          {/* Left Sidebar - Config */}
          <aside className="w-96 flex-shrink-0 border-r border-gray-800 bg-gray-950 sticky top-[57px] h-[calc(100vh-57px)] overflow-y-auto">
            <div className="p-4 space-y-6">
              <ModelSelector
                selectedModels={config.model_ids}
                onChange={(ids) =>
                  setConfig((prev) => ({ ...prev, model_ids: ids }))
                }
                models={models}
              />
              <div className="border-t border-gray-800" />
              <ProbeConfigPanel
                config={config}
                onChange={handleConfigChange}
                onRun={handleRun}
                onStop={stream.stop}
                isRunning={stream.isRunning}
                promptSets={promptSets}
                onPromptSetsChange={loadPromptSets}
              />
            </div>
          </aside>

          {/* Main Content */}
          <main className="flex-1 min-w-0">
            <div className="p-6 space-y-6">
              {/* Progress Bar */}
              <ProgressBar
                completed={stream.progress.completed}
                total={stream.progress.total}
                isRunning={stream.isRunning}
              />

              {/* Error Display */}
              {stream.error && (
                <div className="bg-rose-500/10 border border-rose-500/20 rounded-xl p-4">
                  <div className="flex items-center gap-2">
                    <svg
                      className="w-5 h-5 text-rose-400 flex-shrink-0"
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                      />
                    </svg>
                    <p className="text-sm text-rose-300">{stream.error}</p>
                  </div>
                </div>
              )}

              {/* Stats Cards */}
              <StatsCards results={stream.results} />

              {/* Streaming View */}
              <StreamingView
                tokens={stream.tokens}
                ttfts={stream.ttfts}
                isRunning={stream.isRunning}
              />

              {/* Tab Navigation */}
              {stream.results.length > 0 && (
                <div className="border-b border-gray-800">
                  <nav className="flex gap-1">
                    {(
                      [
                        { key: "results", label: t.resultsTable },
                        { key: "charts", label: t.chartsTab },
                        { key: "compare", label: t.comparisonTab },
                      ] as const
                    ).map((tab) => (
                      <button
                        key={tab.key}
                        onClick={() => setActiveTab(tab.key)}
                        className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                          activeTab === tab.key
                            ? "border-blue-500 text-blue-400"
                            : "border-transparent text-gray-500 hover:text-gray-300"
                        }`}
                      >
                        {tab.label}
                      </button>
                    ))}
                  </nav>
                </div>
              )}

              {/* Tab Content */}
              {stream.results.length > 0 && activeTab === "results" && (
                <ResultsTable results={stream.results} />
              )}
              {stream.results.length > 0 && activeTab === "charts" && (
                <LatencyChart results={stream.results} />
              )}
              {stream.results.length > 0 && activeTab === "compare" && (
                <ComparisonView results={stream.results} />
              )}

              {/* Empty State */}
              {!stream.isRunning &&
                stream.results.length === 0 &&
                !stream.error && (
                  <div className="flex flex-col items-center justify-center py-24 text-center">
                    <div className="w-16 h-16 bg-gray-800 rounded-2xl flex items-center justify-center mb-4">
                      <svg
                        className="w-8 h-8 text-gray-600"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                        strokeWidth={1.5}
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z"
                        />
                      </svg>
                    </div>
                    <h2 className="text-xl font-semibold text-gray-300 mb-2">
                      {t.readyTitle}
                    </h2>
                    <p className="text-gray-500 max-w-md text-sm">
                      {t.readyDesc}
                    </p>
                  </div>
                )}
            </div>
          </main>
        </div>
      )}

      {/* History Panel */}
      <HistoryPanel isOpen={historyOpen} onClose={() => setHistoryOpen(false)} />

      {/* FloatingChat - 미인증 사용자도 버튼 표시. 클릭 시 로그인 모달 → 로그인 후 자동 오픈. */}
      <FloatingChat />

      {/* Header 로그인 버튼이 여는 인증 모달 */}
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
            <LoginForm
              onLoginSuccess={(u) => {
                handleLoginSuccess(u);
                setLoginModalOpen(false);
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
