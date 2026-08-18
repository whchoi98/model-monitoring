"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchMultiChannelReliability,
  MultiChannelReliability,
  ReliabilityChannelRow,
} from "@/lib/api";
import { useLang } from "@/lib/i18n-context";

const WINDOW_OPTIONS = [
  { value: "1h", labelKo: "1시간", labelEn: "1h" },
  { value: "6h", labelKo: "6시간", labelEn: "6h" },
  { value: "24h", labelKo: "24시간", labelEn: "24h" },
  { value: "7d", labelKo: "7일", labelEn: "7d" },
];

const CHANNEL_BG: Record<string, string> = {
  "Bedrock Global": "bg-orange-500/10 light:bg-gray-900/50 border-orange-500/30 text-orange-300",
  "Bedrock US": "bg-pink-500/10 light:bg-gray-900/50 border-pink-500/30 text-pink-300",
  "Anthropic (CP on AWS)": "bg-purple-500/10 light:bg-gray-900/50 border-purple-500/30 text-purple-300",
  // OpenAI channels — Global CRIS + Mantle regions + 1P direct (green family).
  "OpenAI Global": "bg-cyan-500/10 light:bg-gray-900/50 border-cyan-500/30 text-cyan-300",
  "OpenAI us-east-1": "bg-emerald-500/10 light:bg-gray-900/50 border-emerald-500/30 text-emerald-300",
  "OpenAI us-east-2": "bg-green-500/10 light:bg-gray-900/50 border-green-500/30 text-green-300",
  "OpenAI us-west-2": "bg-teal-500/10 light:bg-gray-900/50 border-teal-500/30 text-teal-300",
  "OpenAI 1P": "bg-lime-500/10 light:bg-gray-900/50 border-lime-500/30 text-lime-300",
};

const ERROR_BUCKET_LABELS_KO: Record<string, string> = {
  throttle: "Throttle",
  overloaded: "Overloaded",
  server: "Server 5xx",
  model: "Model error",
  network: "Network",
  other: "기타",
};
const ERROR_BUCKET_LABELS_EN: Record<string, string> = {
  throttle: "Throttle",
  overloaded: "Overloaded",
  server: "Server 5xx",
  model: "Model error",
  network: "Network",
  other: "Other",
};

function formatRate(r: number | null): string {
  if (r === null) return "—";
  return `${(r * 100).toFixed(2)}%`;
}

function rateColor(r: number | null): string {
  if (r === null) return "text-gray-500";
  if (r >= 0.99) return "text-emerald-400";
  if (r >= 0.95) return "text-amber-400";
  return "text-rose-400";
}

export default function ReliabilityPanel() {
  const { lang } = useLang();
  const [windowSpec, setWindowSpec] = useState("24h");
  const [data, setData] = useState<MultiChannelReliability | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await fetchMultiChannelReliability(windowSpec);
      setData(d);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [windowSpec]);

  useEffect(() => {
    load();
  }, [load]);

  const errLabels = lang === "en" ? ERROR_BUCKET_LABELS_EN : ERROR_BUCKET_LABELS_KO;

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">
            {lang === "en" ? "Multi-channel Reliability" : "다중 채널 신뢰성"}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {lang === "en"
              ? "Same model family across Bedrock Global / US, Anthropic CP on AWS, and OpenAI (Mantle regions + 1P direct) channels — for failover decisions."
              : "동일 모델을 Bedrock Global / US, Anthropic CP on AWS, OpenAI(Mantle 리전 + 1P direct) 채널별로 비교 — failover 의사결정용."}
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-gray-400">
            {lang === "en" ? "Window" : "기간"}
          </span>
          <div className="flex gap-1">
            {WINDOW_OPTIONS.map((w) => (
              <button
                key={w.value}
                onClick={() => setWindowSpec(w.value)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  windowSpec === w.value
                    ? "bg-blue-600 text-white"
                    : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                }`}
              >
                {lang === "en" ? w.labelEn : w.labelKo}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-rose-500/10 border border-rose-500/20 rounded-md p-3 text-xs text-rose-400">
          {error}
        </div>
      )}

      {loading ? (
        <div className="text-xs text-gray-500">{lang === "en" ? "Loading..." : "로딩 중..."}</div>
      ) : !data || data.families.length === 0 ? (
        <div className="text-xs text-gray-500">
          {lang === "en" ? "No data in selected window." : "선택한 기간에 데이터가 없습니다."}
        </div>
      ) : (
        <div className="space-y-4">
          {data.families.map((fam) => {
            // family 내 채널 중 최고 성공률 식별 (winner highlight)
            const bestRate = Math.max(
              ...fam.channels.map((c) => c.success_rate ?? 0),
            );
            return (
              <div key={fam.family} className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
                <h2 className="text-base font-semibold text-gray-100 mb-3">{fam.family}</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {fam.channels.map((c) => {
                    const isWinner = c.success_rate !== null && c.success_rate === bestRate;
                    return (
                      <div
                        key={c.channel}
                        className={`rounded-lg border p-3 ${CHANNEL_BG[c.channel] ?? "bg-gray-800 border-gray-700"} ${isWinner ? "ring-1 ring-emerald-500/40" : ""}`}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <div className="text-xs font-semibold">{c.channel}</div>
                          {isWinner && (
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                              {lang === "en" ? "BEST" : "최우수"}
                            </span>
                          )}
                        </div>
                        <div className={`text-2xl font-bold tabular-nums ${rateColor(c.success_rate)}`}>
                          {formatRate(c.success_rate)}
                        </div>
                        <div className="text-[10px] opacity-70 mt-0.5">
                          {c.success}/{c.samples} {lang === "en" ? "success" : "성공"}
                        </div>
                        <div className="text-[10px] mt-2 grid grid-cols-2 gap-x-2 gap-y-0.5">
                          <div className="opacity-70">avg TTFT</div>
                          <div className="text-right tabular-nums">
                            {c.avg_ttft_ms !== null ? `${c.avg_ttft_ms.toFixed(0)} ms` : "—"}
                          </div>
                          <div className="opacity-70">p95 TTFT</div>
                          <div className="text-right tabular-nums">
                            {c.p95_ttft_ms !== null ? `${c.p95_ttft_ms.toFixed(0)} ms` : "—"}
                          </div>
                          <div className="opacity-70">p95 Latency</div>
                          <div className="text-right tabular-nums">
                            {c.p95_latency_ms !== null ? `${(c.p95_latency_ms / 1000).toFixed(2)} s` : "—"}
                          </div>
                          <div className="opacity-70">avg TPS</div>
                          <div className="text-right tabular-nums">
                            {c.avg_tps !== null ? c.avg_tps.toFixed(1) : "—"}
                          </div>
                        </div>
                        {(c.error > 0 || c.overloaded > 0) && (
                          <div className="mt-2 pt-2 border-t border-current/20">
                            <div className="text-[10px] opacity-70 mb-1">
                              {lang === "en" ? "Failure modes" : "실패 유형"}
                            </div>
                            <div className="flex flex-wrap gap-1">
                              {Object.entries(c.error_buckets).map(([k, v]) => (
                                <span
                                  key={k}
                                  className="text-[10px] px-1.5 py-0.5 rounded bg-black/30"
                                >
                                  {errLabels[k] ?? k}: {v}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {/* 방법론 설명 박스 */}
      <div className="bg-gray-900/40 border border-gray-800/60 rounded-xl p-5 space-y-2 text-xs text-gray-400">
        <h3 className="text-sm font-semibold text-gray-200">
          {lang === "en" ? "How we test & decide the BEST channel" : "테스트 방법 및 최우수 판정 기준"}
        </h3>
        <p>
          {lang === "en"
            ? "Every 5 minutes the auto-prober invokes ALL monitored models in round-robin across 6 workload categories (short chat, reasoning, code-gen, summarization, JSON extraction, translation). Same prompt is sent to the SAME-FAMILY model in every channel — so per-channel results are directly comparable."
            : "5분 주기 auto-prober가 6개 워크로드 카테고리(짧은 대화·추론·코드 생성·요약·JSON 추출·번역)를 라운드로빈하며 모니터링 모든 모델을 호출합니다. 같은 family 모델은 모든 채널에 동일한 프롬프트를 보내므로 채널별 결과가 직접 비교 가능합니다."}
        </p>
        <p>
          <span className="text-gray-300 font-semibold">
            {lang === "en" ? "BEST badge criterion" : "BEST 배지 기준"}:
          </span>{" "}
          {lang === "en"
            ? "the channel with the highest success rate within the family in the selected window. Ties (same success rate) are broken by alphabetical channel order."
            : "선택한 기간 내 family 안에서 가장 높은 성공률 채널. 동률이면 채널 이름 알파벳 순."}
        </p>
        <p>
          <span className="text-gray-300 font-semibold">
            {lang === "en" ? "Failure modes" : "실패 유형"}:
          </span>{" "}
          {lang === "en"
            ? "we classify error_message into Throttle / Overloaded / Server 5xx / Model error / Network / Other. Use these to decide failover routing — e.g., if a channel shows recurring Throttle, route bursts elsewhere."
            : "error_message를 Throttle / Overloaded / Server 5xx / Model error / Network / 기타로 분류. 한 채널이 Throttle이 반복되면 burst 트래픽을 다른 채널로 라우팅하는 식의 failover 결정에 사용."}
        </p>
        <p>
          {lang === "en"
            ? "Note: success rate alone is not sufficient — combine with p95 TTFT (perceived speed) and failure-mode patterns. A channel with 99% success but 3× higher p95 TTFT may not be the best choice for a chat use case."
            : "주의: 성공률만으로는 충분하지 않습니다. p95 TTFT(체감 속도)와 실패 유형 패턴을 함께 보세요. 성공률 99%지만 p95 TTFT가 3배 더 긴 채널은 chat 시나리오에 부적합할 수 있습니다."}
        </p>
      </div>
    </div>
  );
}
