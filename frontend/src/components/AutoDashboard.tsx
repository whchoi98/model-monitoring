"use client";

import { useState, useEffect, useCallback } from "react";
import { AutoProbeStatus, ProbeResult, TrendPoint } from "@/lib/types";
import { fetchAutoStatus, fetchAutoLatest, fetchAutoTrend, triggerAutoProbe } from "@/lib/api";
import { Translations } from "@/lib/i18n";
import { useT } from "@/lib/i18n-context";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import ModelStatusGrid from "./ModelStatusGrid";
import TrendChart from "./TrendChart";
import InsightsPanel from "./InsightsPanel";

function formatRelativeTime(isoString: string | null, t: Translations): string {
  if (!isoString) return "-";
  const d = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  if (diffSec < 0) {
    // Future time
    const absSec = Math.abs(diffSec);
    const min = Math.floor(absSec / 60);
    const sec = absSec % 60;
    return `${min}${t.minutes} ${sec}${t.seconds}`;
  }
  if (diffSec < 60) return t.justNow;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return t.minutesAgo(diffMin);
  return t.hoursAgo(Math.floor(diffMin / 60));
}

function formatCountdown(nextRunTime: string | null, t: Translations): string {
  if (!nextRunTime) return "-";
  const d = new Date(nextRunTime);
  const now = new Date();
  const diffSec = Math.max(0, Math.floor((d.getTime() - now.getTime()) / 1000));
  const min = Math.floor(diffSec / 60);
  const sec = diffSec % 60;
  return `${min}${t.minutes} ${sec < 10 ? "0" : ""}${sec}${t.seconds}`;
}

// 시간 단위 + 분 단위 (fractional hours: 0.5h=30m, 0.25h=15m, 0.0833h≈5m).
const TREND_RANGE_HOURS = [168, 120, 72, 24, 12, 6, 3, 1, 0.5, 0.25, 1 / 12];

export default function AutoDashboard() {
  const t = useT();

  const [status, setStatus] = useState<AutoProbeStatus | null>(null);
  const [results, setResults] = useState<ProbeResult[]>([]);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  // 카드 클릭 시 해당 모델만 추세 그래프에 표시.
  const [selectedModel, setSelectedModel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [nextCountdown, setNextCountdown] = useState("-");
  const [trendHours, setTrendHours] = useState(1);

  const loadData = useCallback(async () => {
    try {
      const [s, r, tr] = await Promise.all([
        fetchAutoStatus(),
        fetchAutoLatest(),
        fetchAutoTrend(trendHours),
      ]);
      setStatus(s);
      setResults(r);
      setTrend(tr);
    } catch (err) {
      console.error("Failed to load auto-probe data:", err);
    } finally {
      setLoading(false);
    }
  }, [trendHours]);

  // Initial load + trendHours 변경 시 즉시 reload (loadData identity 의존이 아니라
  // 명시적으로 trendHours를 트리거로 사용해 조회기간 클릭 즉시 그래프가 갱신되도록 보장).
  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trendHours]);

  // Auto-refresh every 30 seconds
  const { countdown, enabled, setEnabled } = useAutoRefresh(loadData, 30000);

  // Update next-run countdown every second
  useEffect(() => {
    const id = setInterval(() => {
      if (status?.next_run_time) {
        setNextCountdown(formatCountdown(status.next_run_time, t));
      }
    }, 1000);
    return () => clearInterval(id);
  }, [status?.next_run_time, t]);

  const handleTrigger = async () => {
    setTriggerLoading(true);
    try {
      await triggerAutoProbe();
      // Reload after a short delay to let the cycle start
      setTimeout(loadData, 2000);
    } catch (err) {
      console.error("Failed to trigger probe:", err);
    } finally {
      setTriggerLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  const hasData = results.length > 0;

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Status Bar */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
        <div className="flex items-center justify-between flex-wrap gap-4">
          <div className="flex items-center gap-6">
            <h2 className="text-sm font-semibold text-gray-200">{t.autoProbeStatus}</h2>

            {/* Last probe */}
            <div className="text-xs text-gray-400">
              <span className="text-gray-600">{t.lastProbe}: </span>
              <span className="text-gray-300">{formatRelativeTime(status?.last_run_time ?? null, t)}</span>
            </div>

            {/* Next probe */}
            <div className="text-xs text-gray-400">
              <span className="text-gray-600">{t.nextProbe}: </span>
              <span className="text-gray-300">{nextCountdown}</span>
            </div>

            {/* Running status */}
            {status?.current_cycle_running && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/10 text-blue-400 border border-blue-500/20">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                {t.cycleRunning}
              </span>
            )}
            {status && !status.current_cycle_running && status.is_running && (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                {t.waiting}
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            {/* Auto-refresh toggle */}
            <label className="flex items-center gap-2 text-xs text-gray-500 cursor-pointer">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="rounded border-gray-600 bg-gray-800 text-blue-500 focus:ring-blue-500 focus:ring-offset-0"
              />
              {t.autoRefresh} ({countdown}{t.seconds})
            </label>

            {/* Trigger button */}
            <button
              onClick={handleTrigger}
              disabled={triggerLoading || status?.current_cycle_running}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {triggerLoading ? t.triggering : t.triggerNow}
            </button>
          </div>
        </div>
      </div>

      {hasData ? (
        <>
          {/* 1) Model Status Grid - 카드 클릭으로 그래프 필터링 가능 */}
          <ModelStatusGrid
            results={results}
            selectedModel={selectedModel}
            onSelectModel={setSelectedModel}
          />

          {/* 2) AI 인사이트 패널 (insights_runner 10분 잡 결과 + 새로고침 버튼) */}
          <InsightsPanel />

          {/* 3) Trend Charts - selectedModel이 있으면 해당 모델만 표시 */}
          {trend.length > 0 && (
            <div className="space-y-4">
              {/* Time Range Selector */}
              <div className="flex items-center gap-3">
                <span className="text-xs font-medium text-gray-400">{t.trendRange}</span>
                <div className="flex gap-1">
                  {TREND_RANGE_HOURS.map((hours) => (
                    <button
                      key={hours}
                      onClick={() => setTrendHours(hours)}
                      className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                        trendHours === hours
                          ? "bg-blue-600 text-white"
                          : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                      }`}
                    >
                      {t.trendRangeLabel(hours)}
                    </button>
                  ))}
                </div>
              </div>

              {/* Model Selector - 모델 칩, 선택 시 해당 그래프만 표시 */}
              <div className="flex items-start gap-3 flex-wrap">
                <span className="text-xs font-medium text-gray-400 pt-1 shrink-0">모델</span>
                <div className="flex gap-1 flex-wrap">
                  <button
                    onClick={() => setSelectedModel(null)}
                    className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                      selectedModel === null
                        ? "bg-blue-600 text-white"
                        : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                    }`}
                  >
                    전체
                  </button>
                  {results.map((r) => (
                    <button
                      key={r.model_id}
                      onClick={() =>
                        setSelectedModel(selectedModel === r.model_name ? null : r.model_name)
                      }
                      className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                        selectedModel === r.model_name
                          ? "bg-blue-600 text-white"
                          : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                      }`}
                    >
                      {r.model_name}
                    </button>
                  ))}
                </div>
              </div>

              <TrendChart data={trend} metric="ttft_ms" title={t.ttftTrend} selectedModel={selectedModel} />
              <TrendChart data={trend} metric="total_latency_ms" title={t.latencyTrend} selectedModel={selectedModel} />
              <TrendChart data={trend} metric="tps" title={t.tpsTrend} selectedModel={selectedModel} />
            </div>
          )}

          {/* 4) Metric Descriptions Panel */}
          <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
            <h3 className="text-sm font-semibold text-gray-200 mb-3">{t.metricDescTitle}</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {Object.entries(t.metrics).map(([key, m]) => (
                <div key={key} className="text-xs">
                  <span className="font-medium text-gray-300">{m.name}</span>
                  <span className="text-gray-600"> ({m.unit})</span>
                  <p className="text-gray-500 mt-0.5 leading-relaxed">{m.desc}</p>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : (
        /* Empty State */
        <div className="flex flex-col items-center justify-center py-24 text-center">
          <div className="w-16 h-16 bg-gray-800 rounded-2xl flex items-center justify-center mb-4">
            <svg className="w-8 h-8 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-gray-300 mb-2">{t.noDataYet}</h2>
          <p className="text-gray-500 max-w-md text-sm">{t.noDataDesc}</p>
          {status?.current_cycle_running && (
            <div className="mt-4 flex items-center gap-2 text-sm text-blue-400">
              <div className="w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              {t.cycleRunning}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
