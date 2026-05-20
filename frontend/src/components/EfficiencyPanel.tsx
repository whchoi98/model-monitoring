"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchEfficiency,
  fetchWorkloadCategories,
  EfficiencyResponse,
} from "@/lib/api";
import { useLang } from "@/lib/i18n-context";
import { formatCost } from "@/lib/pricing";

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
  const [categories, setCategories] = useState<{ id: string; label_ko: string; label_en: string }[]>([]);
  const [data, setData] = useState<EfficiencyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchWorkloadCategories().then(setCategories).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await fetchEfficiency(windowSpec, category);
      setData(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [windowSpec, category]);

  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
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
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-gray-400">{lang === "en" ? "Window" : "기간"}</span>
          <div className="flex gap-1">
            {WINDOW_OPTIONS.map((w) => (
              <button
                key={w.value}
                onClick={() => setWindowSpec(w.value)}
                className={`px-2.5 py-1 text-xs rounded-md ${windowSpec === w.value ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}
              >
                {lang === "en" ? w.labelEn : w.labelKo}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Category chip filter */}
      {categories.length > 0 && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-3 flex items-center gap-2 flex-wrap">
          <span className="text-xs font-medium text-gray-400">
            {lang === "en" ? "Workload" : "워크로드"}
          </span>
          <button
            onClick={() => setCategory(null)}
            className={`px-2.5 py-1 text-xs rounded-md ${category === null ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}
          >
            {lang === "en" ? "All" : "전체"}
          </button>
          {categories.map((c) => (
            <button
              key={c.id}
              onClick={() => setCategory(c.id)}
              className={`px-2.5 py-1 text-xs rounded-md ${category === c.id ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}
            >
              {lang === "en" ? c.label_en : c.label_ko}
            </button>
          ))}
          {category === null && (
            <span className="text-[10px] text-amber-400/70 ml-2">
              {lang === "en"
                ? "Tip: pick a single category for fair comparison (same prompt)."
                : "Tip: 같은 프롬프트 기준 공정 비교를 위해 카테고리를 선택하세요."}
            </span>
          )}
        </div>
      )}

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/20 rounded-md p-3 text-xs text-rose-400">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-xs text-gray-500">{lang === "en" ? "Loading..." : "로딩 중..."}</div>
      ) : !data || data.models.length === 0 ? (
        <div className="text-xs text-gray-500">
          {lang === "en" ? "No data in selected window." : "선택한 기간에 데이터가 없습니다."}
        </div>
      ) : (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800">
                <th className="text-left py-2 pr-3">#</th>
                <th className="text-left py-2 pr-3">Model</th>
                <th className="text-right py-2 px-2">Score</th>
                <th className="text-right py-2 px-2">Success</th>
                <th className="text-right py-2 px-2">Avg out tok</th>
                <th className="text-right py-2 px-2">Avg cost</th>
                <th className="text-right py-2 px-2">Avg latency</th>
                <th className="text-right py-2 px-2">Avg TPS</th>
                <th className="text-right py-2 pl-2">Samples</th>
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
