"use client";

import { useCallback, useEffect, useState } from "react";
import {
  fetchCostSummary,
  fetchChannelCompare,
  CostSummary,
  ChannelCompare,
} from "@/lib/api";
import { useLang } from "@/lib/i18n-context";
import { formatCost } from "@/lib/pricing";

const WINDOW_OPTIONS: { value: string; labelKo: string; labelEn: string }[] = [
  { value: "1h", labelKo: "1시간", labelEn: "1h" },
  { value: "6h", labelKo: "6시간", labelEn: "6h" },
  { value: "24h", labelKo: "24시간", labelEn: "24h" },
  { value: "7d", labelKo: "7일", labelEn: "7d" },
  { value: "30d", labelKo: "30일", labelEn: "30d" },
];

const CHANNEL_COLORS: Record<string, string> = {
  "Bedrock Global": "bg-orange-500/15 text-orange-300 border-orange-500/30",
  "Bedrock US": "bg-pink-500/15 text-pink-300 border-pink-500/30",
  "Bedrock Nova": "bg-lime-500/15 text-lime-300 border-lime-500/30",
  "Anthropic (CP on AWS)": "bg-purple-500/15 text-purple-300 border-purple-500/30",
};

export default function CostDashboardPanel() {
  const { lang } = useLang();
  const [window, setWindow] = useState("24h");
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [channels, setChannels] = useState<ChannelCompare | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, c] = await Promise.all([
        fetchCostSummary(window),
        fetchChannelCompare(window),
      ]);
      setSummary(s);
      setChannels(c);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [window]);

  useEffect(() => {
    load();
  }, [load]);

  // 월 예측: 현재 window의 시간당 비용 × 30일.
  const monthlyEstimate = (() => {
    if (!summary) return null;
    const hours = window.endsWith("d")
      ? parseInt(window) * 24
      : window.endsWith("h")
        ? parseInt(window)
        : 1;
    if (hours === 0) return null;
    const costPerHour = summary.total_cost_usd / hours;
    return costPerHour * 24 * 30;
  })();

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">
            {lang === "en" ? "Cost Dashboard" : "비용 대시보드"}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {lang === "en"
              ? "Token usage × public pricing → estimated USD spend by model and channel."
              : "토큰 사용량 × 공개 단가 → 모델·채널별 추정 비용 (USD)"}
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
                onClick={() => setWindow(w.value)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  window === w.value
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

      {/* Summary cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <div className="text-xs text-gray-500">
            {lang === "en" ? "Total cost" : "총 비용"}
          </div>
          <div className="text-2xl font-bold text-gray-100 tabular-nums mt-1">
            {summary ? formatCost(summary.total_cost_usd) : "—"}
          </div>
          <div className="text-[10px] text-gray-600 mt-1">
            {lang === "en" ? `Last ${window}` : `최근 ${window}`}
          </div>
        </div>
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <div className="text-xs text-gray-500">
            {lang === "en" ? "Input tokens" : "입력 토큰"}
          </div>
          <div className="text-2xl font-bold text-gray-100 tabular-nums mt-1">
            {summary ? summary.total_input_tokens.toLocaleString() : "—"}
          </div>
        </div>
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <div className="text-xs text-gray-500">
            {lang === "en" ? "Output tokens" : "출력 토큰"}
          </div>
          <div className="text-2xl font-bold text-gray-100 tabular-nums mt-1">
            {summary ? summary.total_output_tokens.toLocaleString() : "—"}
          </div>
        </div>
        <div className="bg-gradient-to-br from-blue-500/10 to-purple-500/10 light:bg-none light:bg-gray-900/50 border border-blue-500/30 rounded-xl p-4">
          <div className="text-xs text-blue-300">
            {lang === "en" ? "30-day projection" : "30일 예상"}
          </div>
          <div className="text-2xl font-bold text-blue-100 tabular-nums mt-1">
            {monthlyEstimate !== null ? formatCost(monthlyEstimate) : "—"}
          </div>
          <div className="text-[10px] text-blue-300/70 mt-1">
            {lang === "en"
              ? "Linear extrapolation from current rate"
              : "현재 속도로 단순 외삽"}
          </div>
        </div>
      </div>

      {/* Channel comparison */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
        <h2 className="text-sm font-semibold text-gray-200 mb-3">
          {lang === "en" ? "Channel comparison" : "채널별 비교"}
        </h2>
        {loading ? (
          <div className="text-xs text-gray-500">{lang === "en" ? "Loading..." : "로딩 중..."}</div>
        ) : !channels || channels.channels.length === 0 ? (
          <div className="text-xs text-gray-500">
            {lang === "en" ? "No data in selected window." : "선택한 기간에 데이터가 없습니다."}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            {channels.channels.map((c) => (
              <div
                key={c.channel}
                className={`rounded-lg border p-3 ${CHANNEL_COLORS[c.channel] ?? "bg-gray-800 border-gray-700 text-gray-300"}`}
              >
                <div className="text-xs font-semibold">{c.channel}</div>
                <div className="text-xl font-bold tabular-nums mt-1">{formatCost(c.cost_usd)}</div>
                <div className="text-[10px] opacity-70 mt-1 space-y-0.5">
                  <div>{c.samples.toLocaleString()} {lang === "en" ? "calls" : "호출"}</div>
                  <div>
                    {c.input_tokens.toLocaleString()} in / {c.output_tokens.toLocaleString()} out
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Per-model breakdown */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 overflow-x-auto">
        <h2 className="text-sm font-semibold text-gray-200 mb-3">
          {lang === "en" ? "Per-model breakdown" : "모델별 상세"}
        </h2>
        {loading ? (
          <div className="text-xs text-gray-500">{lang === "en" ? "Loading..." : "로딩 중..."}</div>
        ) : !summary || summary.rows.length === 0 ? (
          <div className="text-xs text-gray-500">
            {lang === "en" ? "No data." : "데이터가 없습니다."}
          </div>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-gray-500 border-b border-gray-800">
                <th className="text-left py-2 pr-3">Model</th>
                <th className="text-left py-2 px-2">Channel</th>
                <th className="text-right py-2 px-2">Calls</th>
                <th className="text-right py-2 px-2">In tok</th>
                <th className="text-right py-2 px-2">Out tok</th>
                <th className="text-right py-2 px-2">Avg / call</th>
                <th className="text-right py-2 pl-2">Total</th>
              </tr>
            </thead>
            <tbody>
              {summary.rows.map((r) => (
                <tr key={r.model_id} className="border-b border-gray-800/50">
                  <td className="py-2 pr-3 text-gray-200" title={r.model_id}>
                    {r.model_name}
                  </td>
                  <td className="py-2 px-2">
                    <span className={`px-1.5 py-0.5 rounded text-[10px] border ${CHANNEL_COLORS[r.channel] ?? ""}`}>
                      {r.channel}
                    </span>
                  </td>
                  <td className="text-right py-2 px-2 tabular-nums text-gray-300">{r.samples}</td>
                  <td className="text-right py-2 px-2 tabular-nums text-gray-400">
                    {r.input_tokens.toLocaleString()}
                  </td>
                  <td className="text-right py-2 px-2 tabular-nums text-gray-400">
                    {r.output_tokens.toLocaleString()}
                  </td>
                  <td className="text-right py-2 px-2 tabular-nums text-gray-300">
                    {formatCost(r.avg_cost_per_call_usd)}
                  </td>
                  <td className="text-right py-2 pl-2 tabular-nums text-gray-100 font-semibold">
                    {formatCost(r.cost_usd)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="text-[10px] text-gray-600 mt-2">
          {lang === "en"
            ? "Cost based on public Bedrock + Anthropic pricing. Excludes failed/overloaded calls."
            : "비용은 Bedrock + Anthropic 공개 단가 기반. 실패/과부하 호출은 제외."}
        </p>
      </div>

      {/* 비용 산정 방법 설명 박스 */}
      <div className="bg-gray-900/40 border border-gray-800/60 rounded-xl p-5 space-y-2 text-xs text-gray-400">
        <h3 className="text-sm font-semibold text-gray-200">
          {lang === "en" ? "How cost is calculated" : "비용 산정 방법"}
        </h3>
        <p>
          <span className="text-gray-300 font-semibold">
            {lang === "en" ? "Formula" : "공식"}:
          </span>{" "}
          <code className="bg-gray-950 px-1.5 py-0.5 rounded text-blue-300">
            cost = input_tokens × input_price/1M + output_tokens × output_price/1M
          </code>
        </p>
        <p>
          {lang === "en"
            ? "Token counts come from each model's response usage object (per-call). Public unit prices are stored in `pricing.py` (backend) and `lib/pricing.ts` (frontend) and must be updated together when AWS/Anthropic publishes new tiers."
            : "토큰 수는 모델 응답의 usage 객체에서 호출별로 수집합니다. 공개 단가는 `pricing.py`(backend) + `lib/pricing.ts`(frontend)에 정의되어 있고 AWS/Anthropic의 단가 변경 시 함께 업데이트해야 합니다."}
        </p>
        <p>
          <span className="text-gray-300 font-semibold">
            {lang === "en" ? "Channel comparison" : "채널 비교"}:
          </span>{" "}
          {lang === "en"
            ? "Bedrock Global / US use cross-region inference profiles; Anthropic (CP on AWS) uses the vendor's external endpoint (aws-external-anthropic.*.api.aws). Unit prices may differ slightly across channels — this dashboard reports the actual numbers, not assumptions."
            : "Bedrock Global / US는 cross-region inference profile, Anthropic CP on AWS는 vendor external endpoint(aws-external-anthropic.*.api.aws)를 사용합니다. 채널별 단가가 다를 수 있으며 본 대시보드는 실측 수치 그대로를 보여줍니다."}
        </p>
        <p>
          <span className="text-gray-300 font-semibold">
            {lang === "en" ? "30-day projection" : "30일 예상"}:
          </span>{" "}
          {lang === "en"
            ? "linear extrapolation — total_cost_in_window ÷ window_hours × 24 × 30. Useful as a rough budget signal but does not account for variable workload or pricing changes."
            : "선택한 기간 비용을 시간당으로 환산해 × 24 × 30으로 단순 외삽. 워크로드 변동·단가 변경은 반영되지 않은 대략적 budget 신호입니다."}
        </p>
        <p>
          {lang === "en"
            ? "Excluded from cost: failed and overloaded calls (we still charge nothing for these, but they wouldn't reflect actual application spend). Cost is built from successful invocations only."
            : "실패·overloaded 호출은 비용 집계에서 제외 (실제 운영 비용을 정확히 반영하기 위해). 성공 호출만 합산합니다."}
        </p>
      </div>
    </div>
  );
}
