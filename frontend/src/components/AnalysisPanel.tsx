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
  const [categories, setCategories] = useState<
    { id: string; label_ko: string; label_en: string }[]
  >([]);
  const [stopData, setStopData] = useState<StopReasonResponse | null>(null);
  const [lengthData, setLengthData] = useState<OutputLengthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchWorkloadCategories().then(setCategories).catch(() => {});
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [stop, len] = await Promise.all([
        fetchStopReasons(windowSpec, category),
        fetchOutputLength(windowSpec, category),
      ]);
      setStopData(stop);
      setLengthData(len);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [windowSpec, category]);

  useEffect(() => {
    load();
  }, [load]);

  // 히스토그램 최댓값 — bar 폭 스케일링
  const maxHistogramCount = lengthData
    ? Math.max(1, ...lengthData.rows.flatMap((r) => r.histogram.map((h) => h.count)))
    : 1;

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold text-gray-100">
          {lang === "en" ? "Output Analysis" : "출력 분석"}
        </h2>
        <span className="text-xs text-gray-500">
          {lang === "en"
            ? "Stop reason distribution + Output token length"
            : "정지 사유 분포 + 출력 토큰 길이"}
        </span>

        <div className="ml-auto flex items-center gap-2">
          <div className="flex bg-gray-800/60 rounded-lg p-0.5">
            {WINDOW_OPTIONS.map((w) => (
              <button
                key={w.value}
                onClick={() => setWindowSpec(w.value)}
                className={`px-3 py-1 text-xs font-medium rounded-md ${
                  windowSpec === w.value
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-gray-200"
                }`}
              >
                {lang === "en" ? w.labelEn : w.labelKo}
              </button>
            ))}
          </div>

          <select
            value={category ?? ""}
            onChange={(e) => setCategory(e.target.value || null)}
            className="bg-gray-800/60 text-gray-200 text-xs rounded-lg px-3 py-1.5 border border-gray-700"
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

          <button
            onClick={load}
            className="px-3 py-1.5 text-xs font-medium text-gray-200 bg-gray-800 hover:bg-gray-700 rounded-lg"
          >
            {lang === "en" ? "Refresh" : "새로고침"}
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-rose-950/50 border border-rose-800/50 text-rose-300 text-sm rounded-lg px-4 py-2">
          {error}
        </div>
      )}

      {loading && !stopData && !lengthData && (
        <div className="text-gray-500 text-sm">{lang === "en" ? "Loading…" : "불러오는 중…"}</div>
      )}

      {/* ───── Stop Reason 분포 ───── */}
      <section className="bg-gray-900/40 border border-gray-800 rounded-xl p-5 space-y-4">
        <div className="flex items-baseline justify-between">
          <h3 className="text-lg font-semibold text-gray-100">
            {lang === "en" ? "Stop Reason Distribution" : "Stop Reason 분포"}
          </h3>
          <span className="text-xs text-gray-500">
            {lang === "en"
              ? "Why each response ended (success only)"
              : "응답이 끝난 이유 (성공 응답만)"}
          </span>
        </div>

        {/* legend */}
        <div className="flex flex-wrap gap-3 text-xs">
          {STOP_REASON_ORDER.map((k) => (
            <div key={k} className="flex items-center gap-1.5">
              <span className={`w-3 h-3 rounded ${STOP_REASON_COLORS[k] ?? "bg-gray-500"}`} />
              <span className="text-gray-400">{labelStopReason(k, lang)}</span>
            </div>
          ))}
        </div>

        {stopData && stopData.rows.length === 0 && (
          <div className="text-gray-500 text-sm">
            {lang === "en" ? "No data in this window" : "이 기간에 데이터 없음"}
          </div>
        )}

        <div className="space-y-2">
          {stopData?.rows.map((r) => (
            <div key={r.model_id} className="grid grid-cols-12 items-center gap-3">
              <div className="col-span-4 text-sm text-gray-300 truncate" title={r.model_name}>
                {r.model_name}
              </div>
              <div className="col-span-7 flex h-6 rounded overflow-hidden bg-gray-800">
                {STOP_REASON_ORDER.filter((k) => (r.counts[k] ?? 0) > 0).map((k) => {
                  const pct = r.percentages[k] ?? 0;
                  return (
                    <div
                      key={k}
                      className={`${STOP_REASON_COLORS[k] ?? "bg-gray-500"} flex items-center justify-center text-[10px] font-medium text-white`}
                      style={{ width: `${pct}%` }}
                      title={`${labelStopReason(k, lang)}: ${r.counts[k]} (${pct}%)`}
                    >
                      {pct >= 8 ? `${pct.toFixed(0)}%` : ""}
                    </div>
                  );
                })}
              </div>
              <div className="col-span-1 text-xs text-gray-500 text-right tabular-nums">
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
      <section className="bg-gray-900/40 border border-gray-800 rounded-xl p-5 space-y-4">
        <div className="flex items-baseline justify-between">
          <h3 className="text-lg font-semibold text-gray-100">
            {lang === "en" ? "Output Length Distribution" : "출력 길이 분포"}
          </h3>
          <span className="text-xs text-gray-500">
            {lang === "en"
              ? "Output tokens per response (success only)"
              : "응답당 출력 토큰 수 (성공 응답만)"}
          </span>
        </div>

        {lengthData && lengthData.rows.length === 0 && (
          <div className="text-gray-500 text-sm">
            {lang === "en" ? "No data in this window" : "이 기간에 데이터 없음"}
          </div>
        )}

        {lengthData && lengthData.rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
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
                      <div className="flex justify-between text-[9px] text-gray-600 mt-0.5">
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
