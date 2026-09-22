"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchStopReasons,
  fetchOutputLength,
  fetchWorkloadCategories,
  StopReasonResponse,
  OutputLengthResponse,
} from "@/lib/api";
import { useLang } from "@/lib/i18n-context";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { DataEmpty, DataError, DataLoading } from "./DataState";
import RefreshControls from "./RefreshControls";

const WINDOW_OPTIONS = [
  { value: "24h", labelKo: "24시간", labelEn: "24h" },
  { value: "7d", labelKo: "7일", labelEn: "7d" },
  { value: "30d", labelKo: "30일", labelEn: "30d" },
];

// stop_reason 색상 매핑 — 정상(녹색), 잘림(주황), 안전성(적색), 기타(회색)
const STOP_REASON_COLORS: Record<string, string> = {
  end_turn: "bg-emerald-500",
  max_tokens: "bg-amber-500",
  stop_sequence: "bg-sky-500",
  tool_use: "bg-violet-500",
  guardrail_intervened: "bg-rose-500",
  content_filtered: "bg-rose-600",
  other: "bg-gray-500",
  unknown: "bg-gray-700",
};

const STOP_REASON_ORDER = [
  "end_turn",
  "max_tokens",
  "stop_sequence",
  "tool_use",
  "guardrail_intervened",
  "content_filtered",
  "other",
  "unknown",
];

function labelStopReason(key: string, lang: "ko" | "en"): string {
  const ko: Record<string, string> = {
    end_turn: "정상 종료",
    max_tokens: "토큰 한도",
    stop_sequence: "정지 시퀀스",
    tool_use: "도구 호출",
    guardrail_intervened: "가드레일",
    content_filtered: "필터링",
    other: "기타",
    unknown: "미상",
  };
  if (lang === "ko") return ko[key] ?? key;
  return key;
}

export default function AnalysisPanel() {
  const { lang } = useLang();
  const [windowSpec, setWindowSpec] = useState("7d");
  const [category, setCategory] = useState<string | null>(null);
  const categoriesResource = useAsyncResource("workload-categories", fetchWorkloadCategories);
  const stopResource = useAsyncResource<StopReasonResponse>(
    `stop-reasons:${windowSpec}:${category ?? "all"}`,
    (signal) => fetchStopReasons(windowSpec, category, signal),
  );
  const lengthResource = useAsyncResource<OutputLengthResponse>(
    `output-length:${windowSpec}:${category ?? "all"}`,
    (signal) => fetchOutputLength(windowSpec, category, signal),
  );
  const categories = categoriesResource.data ?? [];
  const stopData = stopResource.data;
  const lengthData = lengthResource.data;
  const refreshAll = useCallback(async () => {
    await Promise.allSettled([stopResource.refresh(), lengthResource.refresh(), categoriesResource.refresh()]);
  }, [stopResource.refresh, lengthResource.refresh, categoriesResource.refresh]);
  const { enabled, setEnabled, countdown, reset } = useAutoRefresh(refreshAll, 30_000);
  useEffect(reset, [windowSpec, category, reset]);

  // The older successful section determines freshness after a partial refresh.
  const checkedAt = [stopResource.updatedAt, lengthResource.updatedAt].filter((time): time is number => time !== null);
  const updatedAt = checkedAt.length ? Math.min(...checkedAt) : null;

  // 히스토그램 최댓값 — bar 폭 스케일링
  const maxHistogramCount = lengthData
    ? Math.max(1, ...lengthData.rows.flatMap((r) => r.histogram.map((h) => h.count)))
    : 1;

  return (
    <div className="min-w-0 p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">
            {lang === "en" ? "Output Analysis" : "출력 분석"}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {lang === "en"
              ? "Stop reason distribution + Output token length"
              : "정지 사유 분포 + 출력 토큰 길이"}
          </p>
        </div>
        <div role="group" aria-label={lang === "en" ? "Window" : "기간"} className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-gray-400">{lang === "en" ? "Window" : "기간"}</span>
          <div className="flex flex-wrap gap-1">
            {WINDOW_OPTIONS.map((w) => (
              <button
                key={w.value}
                type="button"
                aria-pressed={windowSpec === w.value}
                onClick={() => setWindowSpec(w.value)}
                className={windowSpec === w.value ? "ui-button-primary" : "ui-button"}
              >
                {lang === "en" ? w.labelEn : w.labelKo}
              </button>
            ))}
          </div>
        </div>
      </div>

      <RefreshControls
        refreshing={stopResource.refreshing || lengthResource.refreshing || categoriesResource.refreshing}
        onRefresh={() => { reset(); void refreshAll(); }}
        updatedAt={updatedAt}
        enabled={enabled}
        onEnabledChange={setEnabled}
        countdown={countdown}
      />

      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-3 space-y-3">
        <label className="flex flex-wrap items-center gap-3 text-xs text-gray-400">
          <span>{lang === "en" ? "Workload" : "워크로드"}</span>
          <select
            value={category ?? ""}
            onChange={(e) => setCategory(e.target.value || null)}
            className="ui-input max-w-full text-xs"
          >
            <option value="">
              {lang === "en" ? "All workloads" : "전체 워크로드"}
            </option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {lang === "en" ? c.label_en : c.label_ko}
              </option>
            ))}
          </select>
        </label>
        <DataError
          error={categoriesResource.error}
          resource={lang === "en" ? "workload categories" : "워크로드 카테고리"}
          onRetry={() => { reset(); void categoriesResource.refresh(); }}
          hasData={categoriesResource.data !== null}
        />
        {categoriesResource.loading && <DataLoading />}
        {!categoriesResource.error && !categoriesResource.refreshing && categoriesResource.data?.length === 0 && (
          <DataEmpty
            title={lang === "en" ? "No workload categories available." : "사용할 수 있는 워크로드 카테고리가 없습니다."}
            description={lang === "en" ? "Select All workloads to compare all results." : "전체 워크로드를 선택해 모든 결과를 비교할 수 있습니다."}
          />
        )}
      </div>

      {/* ───── Stop Reason 분포 ───── */}
      <section aria-labelledby="analysis-stop-title" className="min-w-0 bg-gray-900/50 border border-gray-800 rounded-xl p-4 space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="analysis-stop-title" className="text-sm font-semibold text-gray-200">
            {lang === "en" ? "Stop Reason Distribution" : "Stop Reason 분포"}
          </h2>
          <span className="text-xs text-gray-500">
            {lang === "en"
              ? "Why each response ended (success only)"
              : "응답이 끝난 이유 (성공 응답만)"}
          </span>
        </div>

        <DataError
          error={stopResource.error}
          resource={lang === "en" ? "stop reason distribution" : "정지 사유 분포"}
          onRetry={() => { reset(); void stopResource.refresh(); }}
          hasData={stopData !== null}
        />
        {stopResource.loading && <DataLoading />}

        {/* legend */}
        <div className="flex flex-wrap gap-3 text-xs">
          {STOP_REASON_ORDER.map((k) => (
            <div key={k} className="flex items-center gap-1.5">
              <span className={`w-3 h-3 rounded ${STOP_REASON_COLORS[k] ?? "bg-gray-500"}`} />
              <span className="text-gray-400">{labelStopReason(k, lang)}</span>
            </div>
          ))}
        </div>

        {!stopResource.error && !stopResource.refreshing && stopData?.rows.length === 0 && <DataEmpty />}

        <div className="space-y-2">
          {stopData?.rows.map((r) => (
            <div key={r.model_id} className="grid grid-cols-12 items-center gap-x-3 gap-y-2">
              <div className="col-span-12 sm:col-span-4 min-w-0 text-sm text-gray-300 break-words" title={r.model_name}>
                {r.model_name}
              </div>
              <div className="col-span-10 sm:col-span-7 flex h-6 rounded overflow-hidden bg-gray-800">
                {STOP_REASON_ORDER.filter((k) => (r.counts[k] ?? 0) > 0).map((k) => {
                  const pct = r.percentages[k] ?? 0;
                  return (
                    <div
                      key={k}
                      className={`${STOP_REASON_COLORS[k] ?? "bg-gray-500"} flex items-center justify-center text-[11px] font-medium text-white`}
                      style={{ width: `${pct}%` }}
                      title={`${labelStopReason(k, lang)}: ${r.counts[k]} (${pct}%)`}
                    >
                      {pct >= 8 ? `${pct.toFixed(0)}%` : ""}
                    </div>
                  );
                })}
              </div>
              <div className="col-span-2 sm:col-span-1 text-xs text-gray-500 text-right tabular-nums">
                n={r.total}
              </div>
            </div>
          ))}
        </div>

        {/* 해석 박스 */}
        <div className="mt-4 p-3 bg-gray-950/50 border border-gray-800/70 rounded-lg text-xs text-gray-400 leading-relaxed space-y-1">
          <p className="font-semibold text-gray-300">
            {lang === "en" ? "How to read" : "해석 방법"}
          </p>
          <ul className="list-disc list-inside space-y-0.5">
            <li>
              <span className="text-emerald-400">end_turn</span>{" "}
              {lang === "en"
                ? "= model finished naturally. Higher = healthier prompts."
                : "= 모델이 자연스럽게 종료. 높을수록 프롬프트 설계가 적절."}
            </li>
            <li>
              <span className="text-amber-400">max_tokens</span>{" "}
              {lang === "en"
                ? "= response was cut off. Consider raising max_tokens or shortening the task."
                : "= 응답이 잘림. max_tokens를 올리거나 작업을 줄여야 함."}
            </li>
            <li>
              <span className="text-rose-400">guardrail / content_filtered</span>{" "}
              {lang === "en"
                ? "= safety system blocked output. Investigate prompts that trigger this."
                : "= 안전 시스템이 출력을 차단. 어떤 프롬프트가 트리거하는지 점검."}
            </li>
          </ul>
        </div>
      </section>

      {/* ───── Output Length 분포 ───── */}
      <section aria-labelledby="analysis-length-title" className="min-w-0 bg-gray-900/50 border border-gray-800 rounded-xl p-4 space-y-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="analysis-length-title" className="text-sm font-semibold text-gray-200">
            {lang === "en" ? "Output Length Distribution" : "출력 길이 분포"}
          </h2>
          <span className="text-xs text-gray-500">
            {lang === "en"
              ? "Output tokens per response (success only)"
              : "응답당 출력 토큰 수 (성공 응답만)"}
          </span>
        </div>

        <DataError
          error={lengthResource.error}
          resource={lang === "en" ? "output length distribution" : "출력 길이 분포"}
          onRetry={() => { reset(); void lengthResource.refresh(); }}
          hasData={lengthData !== null}
        />
        {lengthResource.loading && <DataLoading />}
        {!lengthResource.error && !lengthResource.refreshing && lengthData?.rows.length === 0 && <DataEmpty />}

        {lengthData && lengthData.rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="text-xs text-gray-500 border-b border-gray-800">
                <tr>
                  <th className="px-2 py-2 text-left">{lang === "en" ? "Model" : "모델"}</th>
                  <th className="px-2 py-2 text-right">n</th>
                  <th className="px-2 py-2 text-right">{lang === "en" ? "median" : "중앙값"}</th>
                  <th className="px-2 py-2 text-right">p95</th>
                  <th className="px-2 py-2 text-right">std</th>
                  <th className="px-2 py-2 text-right">{lang === "en" ? "min/max" : "최소/최대"}</th>
                  <th className="px-2 py-2 text-left w-1/3">{lang === "en" ? "Histogram" : "분포"}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {lengthData.rows.map((r) => (
                  <tr key={r.model_id} className="hover:bg-gray-900/40">
                    <td className="px-2 py-2 text-gray-200 truncate max-w-[260px]" title={r.model_name}>
                      {r.model_name}
                    </td>
                    <td className="px-2 py-2 text-right text-gray-400 tabular-nums">{r.n}</td>
                    <td className="px-2 py-2 text-right text-gray-200 tabular-nums">{r.median.toFixed(0)}</td>
                    <td className="px-2 py-2 text-right text-gray-200 tabular-nums">{r.p95.toFixed(0)}</td>
                    <td className="px-2 py-2 text-right text-gray-400 tabular-nums">{r.std.toFixed(0)}</td>
                    <td className="px-2 py-2 text-right text-gray-500 tabular-nums">
                      {r.min}/{r.max}
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex items-end gap-0.5 h-8">
                        {r.histogram.map((h, i) => (
                          <div
                            key={i}
                            className="flex-1 bg-sky-600/60 hover:bg-sky-500 rounded-t-sm relative group"
                            style={{
                              height: `${(h.count / maxHistogramCount) * 100}%`,
                              minHeight: h.count > 0 ? "2px" : "0",
                            }}
                            title={`${h.bin} tokens: ${h.count}`}
                          />
                        ))}
                      </div>
                      <div className="flex justify-between text-[11px] text-gray-500 mt-0.5">
                        <span>0</span>
                        <span>4k+</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* 해석 박스 */}
        <div className="mt-4 p-3 bg-gray-950/50 border border-gray-800/70 rounded-lg text-xs text-gray-400 leading-relaxed space-y-1">
          <p className="font-semibold text-gray-300">
            {lang === "en" ? "How to read" : "해석 방법"}
          </p>
          <ul className="list-disc list-inside space-y-0.5">
            <li>
              {lang === "en"
                ? "median vs p95 gap shows variability — wide gap = inconsistent length."
                : "중앙값과 p95의 차이가 변동성. 차이가 크면 응답 길이가 들쭉날쭉."}
            </li>
            <li>
              {lang === "en"
                ? "Higher mean = higher cost and longer latency for the same workload."
                : "평균이 클수록 동일 작업에 비용·지연이 큼."}
            </li>
            <li>
              {lang === "en"
                ? "Bars on the right (1000+) suggest the model tends to over-explain."
                : "오른쪽(1000+) 막대가 크면 모델이 장황한 경향."}
            </li>
            <li>
              {lang === "en"
                ? "Compare same category across models to gauge verbosity differences."
                : "같은 카테고리에서 모델 간 비교 시 verbosity 차이가 보임."}
            </li>
          </ul>
        </div>
      </section>
    </div>
  );
}
