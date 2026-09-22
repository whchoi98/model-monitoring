"use client";

// 정적 캐시 비활성화 - 매 요청마다 dynamic SSR 보장.
// CloudFront/브라우저가 옛 HTML(옛 buildId chunk URL 포함)을 캐시해 매 deploy마다
// chunk 404 + 빈 화면이 반복되는 문제 영구 회피.
// 응답 헤더가 자동으로 `cache-control: no-store, must-revalidate, max-age=0`로 설정됨.
export const dynamic = "force-dynamic";

import { Suspense, useState, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { ModelInfo, ProbeConfig, PromptSet } from "@/lib/types";
import { fetchModels, fetchPromptSets } from "@/lib/api";
import { useT, useLang } from "@/lib/i18n-context";
import { useAuth } from "@/lib/auth-context";
import AppShell from "@/components/AppShell";
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
    <Suspense fallback={<HomeFallback />}>
      <HomeContent />
    </Suspense>
  );
}

function HomeFallback() {
  const { lang } = useLang();
  return (
    <AppShell navKey="dashboard">
      <p role="status" className="p-6 text-sm text-gray-400">{lang === "en" ? "Loading…" : "불러오는 중…"}</p>
    </AppShell>
  );
}

function HomeContent() {
  const t = useT();
  const { lang } = useLang();

  const searchParams = useSearchParams();
  const topTab: TopTab = searchParams.get("view") === "manual" ? "manual" : "dashboard";
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [promptSets, setPromptSets] = useState<PromptSet[]>([]);
  const [config, setConfig] = useState<ProbeConfig>(DEFAULT_CONFIG);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<"results" | "charts" | "compare">(
    "results"
  );

  const { user, checking, openLogin } = useAuth();
  const stream = useProbeStream();

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

  return (
    <AppShell
      navKey={topTab}
      actions={
        <button
          type="button"
          onClick={() => setHistoryOpen(true)}
          className="flex min-h-10 items-center gap-2 px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-gray-100 rounded-lg transition-colors text-xs"
        >
          <svg aria-hidden="true" className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {t.history}
        </button>
      }
    >
      {/* Dashboard Tab */}
      {topTab === "dashboard" && <AutoDashboard />}

      {/* Manual Probe Tab */}
      {topTab === "manual" && (
        <div className="border-b border-gray-800 px-4 py-4 sm:px-6">
          <h1 className="text-xl font-semibold text-gray-100">{t.manualProbeTab}</h1>
        </div>
      )}
      {topTab === "manual" && !user && (
        <div className="mx-auto max-w-md space-y-4 p-6">
          <p role={checking ? "status" : undefined} className="text-sm text-gray-400">
            {checking
              ? (lang === "en" ? "Checking sign-in…" : "로그인 상태 확인 중…")
              : (lang === "en" ? "Sign in to configure and run manual probes." : "수동 프로브 설정과 실행은 로그인 후 이용할 수 있습니다.")}
          </p>
          <button type="button" onClick={() => openLogin()} disabled={checking}
            className="min-h-10 rounded-lg bg-blue-600 px-4 text-sm font-medium text-white disabled:opacity-50">
            {lang === "en" ? "Login" : "로그인"}
          </button>
        </div>
      )}

      {topTab === "manual" && user && (
        <div className="flex flex-col lg:flex-row">
          {/* Left Sidebar - Config */}
          <aside className="w-full lg:w-96 flex-shrink-0 border-b lg:border-b-0 lg:border-r border-gray-800 bg-gray-950 lg:sticky lg:top-[var(--app-header-height,7rem)] lg:h-[calc(100dvh-var(--app-header-height,7rem))] overflow-y-auto">
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
          <div className="flex-1 min-w-0">
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
          </div>
        </div>
      )}

      {/* History Panel */}
      <HistoryPanel isOpen={historyOpen} onClose={() => setHistoryOpen(false)} />
    </AppShell>
  );
}
