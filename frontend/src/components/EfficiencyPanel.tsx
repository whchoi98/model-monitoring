"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchEfficiency,
  fetchWorkloadCategories,
  EfficiencyResponse,
} from "@/lib/api";
import { useLang } from "@/lib/i18n-context";
import { formatCost } from "@/lib/pricing";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { DataEmpty, DataError, DataLoading } from "./DataState";
import RefreshControls from "./RefreshControls";

const WINDOW_OPTIONS = [
  { value: "1h", labelKo: "1시간", labelEn: "1h" },
  { value: "6h", labelKo: "6시간", labelEn: "6h" },
  { value: "24h", labelKo: "24시간", labelEn: "24h" },
  { value: "7d", labelKo: "7일", labelEn: "7d" },
];

function scoreColor(s: number | null): string {
  if (s === null) return "text-gray-500";
  if (s >= 80) return "text-emerald-400";
  if (s >= 60) return "text-amber-400";
  return "text-rose-400";
}

export default function EfficiencyPanel() {
  const { lang } = useLang();
  const [windowSpec, setWindowSpec] = useState("24h");
  const [category, setCategory] = useState<string | null>(null);
  const categoriesResource = useAsyncResource("workload-categories", fetchWorkloadCategories);
  const resource = useAsyncResource<EfficiencyResponse>(
    `efficiency:${windowSpec}:${category ?? "all"}`,
    (signal) => fetchEfficiency(windowSpec, category, signal),
  );
  const categories = categoriesResource.data ?? [];
  const { data } = resource;
  const refreshAll = useCallback(async () => {
    await Promise.allSettled([resource.refresh(), categoriesResource.refresh()]);
  }, [resource.refresh, categoriesResource.refresh]);
  const { enabled, setEnabled, countdown, reset } = useAutoRefresh(refreshAll, 30_000);
  useEffect(reset, [windowSpec, category, reset]);

  return (
    <div className="min-w-0 p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">
            {lang === "en" ? "Token Efficiency" : "토큰 효율성"}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {lang === "en"
              ? "Composite score combining cost, output tokens, latency, TPS, and success rate. Compare models on the same prompt category for a fair view."
              : "비용·출력 토큰·지연·TPS·성공률을 종합한 점수. 같은 카테고리에서 모델 간 공정 비교용."}
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
        refreshing={resource.refreshing || categoriesResource.refreshing}
        onRefresh={() => { reset(); void refreshAll(); }}
        updatedAt={resource.updatedAt}
        enabled={enabled}
        onEnabledChange={setEnabled}
        countdown={countdown}
      />

      {/* Category chip filter */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-3 space-y-3">
        <div role="group" aria-label={lang === "en" ? "Workload" : "워크로드"} className="flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium text-gray-400">
            {lang === "en" ? "Workload" : "워크로드"}
          </span>
          <button
            type="button"
            aria-pressed={category === null}
            onClick={() => setCategory(null)}
            className={category === null ? "ui-button-primary" : "ui-button"}
          >
            {lang === "en" ? "All" : "전체"}
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              type="button"
              aria-pressed={category === c.id}
              onClick={() => setCategory(c.id)}
              className={category === c.id ? "ui-button-primary" : "ui-button"}
            >
              {lang === "en" ? c.label_en : c.label_ko}
            </button>
          ))}
          {category === null && (
            <span className="text-[11px] text-amber-400">
              {lang === "en"
                ? "Tip: pick a single category for fair comparison (same prompt)."
                : "Tip: 같은 프롬프트 기준 공정 비교를 위해 카테고리를 선택하세요."}
            </span>
          )}
        </div>
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
            description={lang === "en" ? "Select All to compare all workloads." : "전체를 선택해 모든 워크로드를 비교할 수 있습니다."}
          />
        )}
      </div>

      <DataError
        error={resource.error}
        resource={lang === "en" ? "token efficiency" : "토큰 효율성"}
        onRetry={() => { reset(); void resource.refresh(); }}
        hasData={data !== null}
      />
      {resource.loading && <DataLoading />}
      {!resource.error && !resource.refreshing && data?.models.length === 0 && <DataEmpty />}
      {data && data.models.length > 0 && (
        <div className="min-w-0 bg-gray-900/50 border border-gray-800 rounded-xl p-4 overflow-x-auto">
          <table className="w-full min-w-[720px] text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800">
                <th className="text-left py-2 pr-3">#</th>
                <th className="text-left py-2 pr-3">{lang === "en" ? "Model" : "모델"}</th>
                <th className="text-right py-2 px-2">{lang === "en" ? "Score" : "점수"}</th>
                <th className="text-right py-2 px-2">{lang === "en" ? "Success" : "성공률"}</th>
                <th className="text-right py-2 px-2">{lang === "en" ? "Avg out tok" : "평균 출력 토큰"}</th>
                <th className="text-right py-2 px-2">{lang === "en" ? "Avg cost" : "평균 비용"}</th>
                <th className="text-right py-2 px-2">{lang === "en" ? "Avg latency" : "평균 지연"}</th>
                <th className="text-right py-2 px-2">{lang === "en" ? "Avg TPS" : "평균 TPS"}</th>
                <th className="text-right py-2 pl-2">{lang === "en" ? "Samples" : "표본 수"}</th>
              </tr>
            </thead>
            <tbody>
              {data.models.map((m, i) => (
                <tr key={m.model_id} className="border-b border-gray-800/50">
                  <td className="py-2 pr-3 text-gray-500 tabular-nums">{i + 1}</td>
                  <td className="py-2 pr-3 text-gray-200" title={m.model_id}>{m.model_name}</td>
                  <td className={`text-right py-2 px-2 tabular-nums font-bold ${scoreColor(m.score)}`}>
                    {m.score !== null ? m.score.toFixed(1) : "—"}
                  </td>
                  <td className="text-right py-2 px-2 tabular-nums text-gray-300">
                    {m.success_rate !== null ? `${(m.success_rate * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td className="text-right py-2 px-2 tabular-nums text-gray-300">
                    {m.avg_output_tokens !== null ? m.avg_output_tokens.toFixed(0) : "—"}
                  </td>
                  <td className="text-right py-2 px-2 tabular-nums text-gray-300">
                    {formatCost(m.avg_cost_usd)}
                  </td>
                  <td className="text-right py-2 px-2 tabular-nums text-gray-300">
                    {m.avg_total_latency_ms !== null ? `${(m.avg_total_latency_ms / 1000).toFixed(2)} s` : "—"}
                  </td>
                  <td className="text-right py-2 px-2 tabular-nums text-gray-300">
                    {m.avg_tps !== null ? m.avg_tps.toFixed(1) : "—"}
                  </td>
                  <td className="text-right py-2 pl-2 tabular-nums text-gray-500">{m.samples}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* 평가 방법 안내 박스 */}
      <div className="bg-gray-900/40 border border-gray-800/60 rounded-xl p-5 space-y-2 text-xs text-gray-400">
        <h3 className="text-sm font-semibold text-gray-200">
          {lang === "en" ? "How the score is calculated" : "점수 계산 방법"}
        </h3>
        <p>
          {lang === "en"
            ? "For each model in the selected window (and optional workload category), we aggregate per-call metrics and compose a 0~100 score using weighted, min-max-normalized components:"
            : "선택한 기간(과 워크로드 카테고리)의 모델별 호출 결과를 집계해, 카테고리 내 min-max 정규화 후 가중 합산해 0~100 점수를 계산합니다:"}
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li>{lang === "en" ? "Cost (30%, inverse) — lower USD per call is better" : "비용 (30%, 역수) — 호출당 USD가 낮을수록 좋음"}</li>
          <li>{lang === "en" ? "Output tokens (25%, inverse) — concise answers preferred" : "출력 토큰 (25%, 역수) — 간결한 응답 선호"}</li>
          <li>{lang === "en" ? "Latency (20%, inverse) — shorter total latency is better" : "지연 (20%, 역수) — 짧을수록 좋음"}</li>
          <li>{lang === "en" ? "TPS (15%, direct) — faster generation is better" : "TPS (15%, 직접) — 빠를수록 좋음"}</li>
          <li>{lang === "en" ? "Success rate (10%, direct)" : "성공률 (10%, 직접)"}</li>
        </ul>
        <p>
          {lang === "en"
            ? "Picking a single category ensures all models receive the SAME prompt — making cost/tokens directly comparable. Without a category, the comparison mixes different prompts and is only a rough indicator."
            : "단일 카테고리를 선택하면 모든 모델이 같은 프롬프트를 받아 비용/토큰 비교가 정확해집니다. 카테고리 미선택 시 서로 다른 프롬프트가 섞여 대략적 지표가 됩니다."}
        </p>
      </div>
    </div>
  );
}
