"use client";

import { useState, useEffect, useCallback } from "react";
import { ModelInfo, ProbeConfig, PromptSet, AuthUser } from "@/lib/types";
import { fetchModels, fetchPromptSets, fetchMe, setToken, getToken } from "@/lib/api";
import { ko } from "@/lib/i18n";
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
                {ko.appTitle}
              </h1>
              <p className="text-xs text-gray-500">
                {ko.appDesc}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
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
                {ko.dashboardTab}
              </button>
              <button
                onClick={() => setTopTab("manual")}
                className={`px-4 py-1.5 text-sm font-medium rounded-md transition-colors ${
                  topTab === "manual"
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                {ko.manualProbeTab}
              </button>
            </nav>

            {/* User info / Logout */}
            {user && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400">{user.username}</span>
                <button
                  onClick={handleLogout}
                  className="px-3 py-1.5 text-xs font-medium text-gray-400 hover:text-gray-200 bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors"
                >
                  {ko.logout}
                </button>
              </div>
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
              {ko.history}
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
          <aside className="w-72 flex-shrink-0 border-r border-gray-800 bg-gray-950 sticky top-[57px] h-[calc(100vh-57px)] overflow-y-auto">
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
                        { key: "results", label: ko.resultsTable },
                        { key: "charts", label: ko.chartsTab },
                        { key: "compare", label: ko.comparisonTab },
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
                      {ko.readyTitle}
                    </h2>
                    <p className="text-gray-500 max-w-md text-sm">
                      {ko.readyDesc}
                    </p>
                  </div>
                )}
            </div>
          </main>
        </div>
      )}

      {/* History Panel */}
      <HistoryPanel isOpen={historyOpen} onClose={() => setHistoryOpen(false)} />
    </div>
  );
}
