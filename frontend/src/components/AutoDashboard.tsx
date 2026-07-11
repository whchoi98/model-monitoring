"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { AutoProbeStatus, ProbeResult, TrendPoint, WorkloadCategory } from "@/lib/types";
import { fetchAutoStatus, fetchAutoLatest, fetchAutoTrend, triggerAutoProbe, fetchWorkloadCategories } from "@/lib/api";
import { Translations } from "@/lib/i18n";
import { useT, useLang } from "@/lib/i18n-context";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { isExcludedModel } from "@/lib/sortModels";
import { buildTrendQuery, defaultTrendSelection, parseTrendQuery } from "@/lib/trendSelection";
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

// 시간 단위 + 분 단위 (fractional hours: 0.5h=30m, 0.25h=15m, 1/6h=10m, 1/12h≈5m).
const TREND_RANGE_HOURS = [168, 120, 72, 24, 12, 6, 3, 1, 0.5, 0.25, 1 / 6, 1 / 12];

export default function AutoDashboard() {
  const t = useT();
  const { lang } = useLang();

  // URL query에서 초기 상태 복원 (v2.7.1: 새로고침 유지 + 링크 공유). SSR 중엔 window 없음.
  const initialQuery =
    typeof window !== "undefined" ? parseTrendQuery(window.location.search) : undefined;

  const [status, setStatus] = useState<AutoProbeStatus | null>(null);
  const [results, setResults] = useState<ProbeResult[]>([]);
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  // 카드/칩/범례 클릭 시 해당 모델만 추세 그래프에 표시 (다중 선택 - Set 토글).
  // 기본값은 전체(빈 set). 대표 모델 자동 선택(v2.7.1)은 카드 그리드 하이라이트와 연동되어
  // 첫 진입 시 일부 카드가 선택된 것처럼 보이는 혼란을 유발해 제거 (2026-07-10 사용자 피드백)
  // — "대표 모델"은 버튼으로만 제공하고, 공유 링크(URL models)는 그대로 복원한다.
  const [selectedModels, setSelectedModels] = useState<Set<string>>(
    initialQuery?.models ?? new Set(),
  );
  // Phase 3 Workload Preset - 선택된 카테고리 필터 (null = 전체).
  const [categories, setCategories] = useState<WorkloadCategory[]>([]);
  const [selectedCategory, setSelectedCategory] = useState<string | null>(
    initialQuery?.category ?? null,
  );
  const toggleModel = (name: string) => {
    setSelectedModels((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };
  const clearSelection = () => setSelectedModels(new Set());
  const [anomalies, setAnomalies] = useState<{
    hours: number;
    total_probes: number;
    total_failures: number;
    models: { model_name: string; failures: number; total: number; last_error: string | null }[];
  } | null>(null);
  const [loading, setLoading] = useState(true);
  // 필터(카테고리/조회기간) 변경·자동새로고침 등 재조회 중 표시 — 최초 로드(loading)와 별개.
  const [refreshing, setRefreshing] = useState(false);
  const [triggerLoading, setTriggerLoading] = useState(false);
  const [nextCountdown, setNextCountdown] = useState("-");
  const [trendHours, setTrendHours] = useState(
    initialQuery?.hours !== undefined && TREND_RANGE_HOURS.includes(initialQuery.hours)
      ? initialQuery.hours
      : 1,
  );
  // 연속 클릭 시 이전 요청 취소 — 느린 이전 응답이 나중에 도착해 최신 선택을 덮어쓰는 경쟁 상태 방지.
  const abortRef = useRef<AbortController | null>(null);

  const loadData = useCallback(async (opts?: { skipStatus?: boolean }) => {
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setRefreshing(true);
    try {
      const [r, tr, s] = await Promise.all([
        fetchAutoLatest(selectedCategory, ac.signal),
        fetchAutoTrend(trendHours, selectedCategory, ac.signal),
        // status는 필터와 무관 — 필터 변경 재조회에서는 생략 (30초 자동새로고침이 갱신).
        opts?.skipStatus ? Promise.resolve(null) : fetchAutoStatus(ac.signal),
      ]);
      if (ac.signal.aborted) return;
      if (s) setStatus(s);
      setResults(r.filter((row) => !isExcludedModel(row.model_name)));
      setTrend(tr.filter((p) => !isExcludedModel(p.model_name)));
    } catch (err) {
      if ((err as Error)?.name !== "AbortError") {
        console.error("Failed to load auto-probe data:", err);
      }
    } finally {
      // 더 새로운 요청이 이미 시작됐다면 그 요청의 표시 상태를 건드리지 않는다.
      if (abortRef.current === ac) setRefreshing(false);
      setLoading(false);
    }
  }, [trendHours, selectedCategory]);

  // 카테고리 목록 1회 fetch.
  useEffect(() => {
    fetchWorkloadCategories().then(setCategories).catch(() => {});
  }, []);

  // 최근 12시간 이상 징후 요약 — 새 프로브가 반영될 때마다 갱신 (v2.12.0).
  useEffect(() => {
    fetch("/api/auto-probe/anomalies?hours=12")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setAnomalies)
      .catch(() => {});
  }, [status?.last_run_time]);

  // Initial load + trendHours/카테고리 변경 시 즉시 reload (loadData identity 의존이 아니라
  // 명시적으로 trendHours를 트리거로 사용해 조회기간 클릭 즉시 그래프가 갱신되도록 보장).
  const isFirstLoad = useRef(true);
  useEffect(() => {
    loadData({ skipStatus: !isFirstLoad.current });
    isFirstLoad.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trendHours, selectedCategory]);

  // 선택 상태를 URL query에 반영 — 새로고침 유지 + 공유 가능한 링크.
  // (replaceState: 히스토리 오염 없이 갱신.)
  useEffect(() => {
    const qs = buildTrendQuery(selectedModels, trendHours, selectedCategory);
    window.history.replaceState(null, "", `${window.location.pathname}${qs}`);
  }, [selectedModels, trendHours, selectedCategory]);

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
      {/* 최근 12시간 이상 징후 (v2.12.0) */}
      {anomalies && (
        anomalies.total_failures > 0 ? (
          <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl px-4 py-3">
            <div className="flex items-center gap-2 flex-wrap text-sm">
              <span className="w-2 h-2 rounded-full bg-rose-400 animate-pulse" />
              <span className="font-semibold text-rose-300">
                {lang === "en"
                  ? `${anomalies.total_failures} anomalies in the last 12h`
                  : `최근 12시간 이상 징후 ${anomalies.total_failures}건`}
              </span>
              <span className="text-xs text-gray-500">
                ({lang === "en" ? `${anomalies.total_probes} probes` : `프로브 ${anomalies.total_probes}회 중`})
              </span>
            </div>
            <div className="flex items-center gap-1.5 flex-wrap mt-2">
              {anomalies.models.slice(0, 8).map((m) => (
                <span
                  key={m.model_name}
                  title={m.last_error ?? undefined}
                  className="px-2 py-0.5 text-[11px] rounded-full bg-rose-500/10 border border-rose-500/30 text-rose-300"
                >
                  {m.model_name} ×{m.failures}
                </span>
              ))}
              {anomalies.models.length > 8 && (
                <span className="text-[11px] text-gray-500">
                  {lang === "en" ? `+${anomalies.models.length - 8} more` : `외 ${anomalies.models.length - 8}개 모델`}
                </span>
              )}
            </div>
          </div>
        ) : (
          <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-xl px-4 py-2.5 flex items-center gap-2 text-sm">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span className="text-emerald-300 font-medium">
              {lang === "en" ? "No anomalies in the last 12h" : "최근 12시간 이상 징후 없음"}
            </span>
            <span className="text-xs text-gray-500">
              {lang === "en"
                ? `all ${anomalies.total_probes} probes succeeded`
                : `프로브 ${anomalies.total_probes}회 전체 성공`}
            </span>
          </div>
        )
      )}

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

      {/* Workload Category 필터 - Phase 3 */}
      {categories.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-3 flex items-center gap-3 flex-wrap">
          <span className="text-xs font-medium text-gray-400">
            {t.workloadLabel ?? "Workload"}
          </span>
          <button
            onClick={() => setSelectedCategory(null)}
            className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
              selectedCategory === null
                ? "bg-blue-600 text-white"
                : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
            }`}
          >
            {t.workloadAll ?? "All"}
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelectedCategory(c.id)}
              title={c.id}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                selectedCategory === c.id
                  ? "bg-blue-600 text-white"
                  : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
              }`}
            >
              {lang === "en" ? c.label_en : c.label_ko}
            </button>
          ))}
        </div>
      )}

      {hasData ? (
        <div
          className={`relative space-y-6 transition-opacity duration-200 ${
            refreshing ? "opacity-60" : ""
          }`}
        >
          {/* 재조회 중 표시 — 필터 클릭이 묵묵히 멈춘 것처럼 보이지 않게 즉각 피드백 */}
          {refreshing && (
            <div className="absolute -top-2 left-1/2 -translate-x-1/2 z-30 flex items-center gap-2 px-3 py-1.5 rounded-full bg-gray-800/90 border border-gray-700 text-xs text-blue-300 shadow-lg">
              <span className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
              {t.refreshing}
            </div>
          )}
          {/* 1) Model Status Grid - 카드 클릭으로 그래프 다중 선택/해제 */}
          <ModelStatusGrid
            results={results}
            selectedModels={selectedModels}
            onToggleModel={toggleModel}
          />

          {/* 2) Trend Charts - selectedModel이 있으면 해당 모델만 표시 */}
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

              {/* Model Selector - 다중 선택 (Set 토글). 전체 = 빈 set. */}
              <div className="flex items-start gap-3 flex-wrap">
                <span className="text-xs font-medium text-gray-400 pt-1 shrink-0">
                  모델 {selectedModels.size > 0 && `(${selectedModels.size}개 선택)`}
                </span>
                <div className="flex gap-1 flex-wrap">
                  <button
                    onClick={clearSelection}
                    className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                      selectedModels.size === 0
                        ? "bg-blue-600 text-white"
                        : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                    }`}
                  >
                    {t.allModels}
                  </button>
                  <button
                    onClick={() =>
                      setSelectedModels(defaultTrendSelection(results.map((r) => r.model_name)))
                    }
                    className="px-2.5 py-1 text-xs rounded-md transition-colors bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                    title={t.repModelsHint}
                  >
                    {t.repModels}
                  </button>
                  {results.map((r) => {
                    const isSelected = selectedModels.has(r.model_name);
                    return (
                      <button
                        key={r.model_id}
                        onClick={() => toggleModel(r.model_name)}
                        className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                          isSelected
                            ? "bg-blue-600 text-white"
                            : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                        }`}
                      >
                        {isSelected ? "✓ " : ""}{r.model_name}
                      </button>
                    );
                  })}
                </div>
              </div>

              <TrendChart data={trend} metric="ttft_ms" title={t.ttftTrend} selectedModels={selectedModels} onToggleModel={toggleModel} />
              <TrendChart data={trend} metric="total_latency_ms" title={t.latencyTrend} selectedModels={selectedModels} onToggleModel={toggleModel} />
              <TrendChart data={trend} metric="tps" title={t.tpsTrend} selectedModels={selectedModels} onToggleModel={toggleModel} />
            </div>
          )}

          {/* 3) AI 인사이트 패널 - 그래프 밑으로 이동 (사용자 요청) */}
          <InsightsPanel />

          {/* 4) Channel Descriptions Panel - 호출 채널/Endpoint 설명 */}
          <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
            <h3 className="text-sm font-semibold text-gray-200 mb-3">{t.channelDescTitle}</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {(["bedrock", "anthropic"] as const).map((k) => (
                <div key={k} className="text-xs space-y-1.5 bg-gray-950/50 border border-gray-800 rounded-md p-3">
                  <div className="flex items-center gap-2">
                    <span className={`inline-block w-2 h-2 rounded-full ${k === "bedrock" ? "bg-orange-400" : "bg-purple-400"}`} />
                    <span className="font-semibold text-gray-200">{t.channels[k].name}</span>
                  </div>
                  <p className="text-gray-500 leading-relaxed">{t.channels[k].desc}</p>
                  <div className="text-gray-600">
                    <span className="text-gray-500">Endpoint: </span>
                    <code className="text-blue-300 break-all">{t.channels[k].endpoint}</code>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* 5) Metric Descriptions Panel */}
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
        </div>
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
