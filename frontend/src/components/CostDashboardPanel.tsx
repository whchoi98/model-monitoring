"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  fetchCostSummary,
  fetchChannelCompare,
  CostSummary,
  ChannelCompare,
} from "@/lib/api";
import { useLang } from "@/lib/i18n-context";
import { formatCost } from "@/lib/pricing";
import { projectMonthlyCost } from "@/lib/costProjection";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { DataEmpty, DataError, DataLoading } from "./DataState";
import RefreshControls from "./RefreshControls";

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
  const summaryResource = useAsyncResource<CostSummary>(
    `cost-summary:${window}`,
    (signal) => fetchCostSummary(window, signal),
  );
  const channelsResource = useAsyncResource<ChannelCompare>(
    `cost-channels:${window}`,
    (signal) => fetchChannelCompare(window, signal),
  );
  const summary = summaryResource.data;
  const channels = channelsResource.data;
  const refreshAll = useCallback(async () => {
    await Promise.allSettled([summaryResource.refresh(), channelsResource.refresh()]);
  }, [summaryResource.refresh, channelsResource.refresh]);
  const { enabled, setEnabled, countdown, reset } = useAutoRefresh(refreshAll, 30_000);
  useEffect(reset, [window, reset]);

  // Use the oldest successful dataset so a partial refresh does not overstate freshness.
  const checkedAt = [summaryResource.updatedAt, channelsResource.updatedAt].filter((time): time is number => time !== null);
  const updatedAt = checkedAt.length ? Math.min(...checkedAt) : null;
  const monthlyEstimate = projectMonthlyCost(summary);

  return (
    <div className="min-w-0 p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">
            {lang === "en" ? "Cost Dashboard" : "비용 대시보드"}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {lang === "en"
              ? "Token usage × official unit prices → estimated USD spend by model and channel."
              : "토큰 사용량 × 공식 단가 → 모델, 채널별 추정 비용 (USD)"}
          </p>
        </div>
        <div role="group" aria-label={lang === "en" ? "Window" : "기간"} className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-gray-400">
            {lang === "en" ? "Window" : "기간"}
          </span>
          <div className="flex flex-wrap gap-1">
            {WINDOW_OPTIONS.map((w) => (
              <button
                key={w.value}
                type="button"
                aria-pressed={window === w.value}
                onClick={() => setWindow(w.value)}
                className={window === w.value ? "ui-button-primary" : "ui-button"}
              >
                {lang === "en" ? w.labelEn : w.labelKo}
              </button>
            ))}
          </div>
        </div>
      </div>

      <RefreshControls
        refreshing={summaryResource.refreshing || channelsResource.refreshing}
        onRefresh={() => { reset(); void refreshAll(); }}
        updatedAt={updatedAt}
        enabled={enabled}
        onEnabledChange={setEnabled}
        countdown={countdown}
      />

      <DataError
        error={summaryResource.error}
        resource={lang === "en" ? "cost summary and model breakdown" : "비용 요약 및 모델별 상세"}
        onRetry={() => { reset(); void summaryResource.refresh(); }}
        hasData={summary !== null}
      />

      {/* Summary cards */}
      <div aria-busy={summaryResource.refreshing} className="grid grid-cols-1 md:grid-cols-4 gap-3">
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
          <div className="text-xs text-gray-500">
            {lang === "en" ? "Total cost" : "총 비용"}
          </div>
          <div className="text-2xl font-bold text-gray-100 tabular-nums mt-1">
            {summary ? formatCost(summary.total_cost_usd) : "—"}
          </div>
          <div className="text-[11px] text-gray-500 mt-1">
            {lang === "en" ? `Last ${summary?.window ?? window}` : `최근 ${summary?.window ?? window}`}
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
          <div className="text-2xl font-bold text-blue-200 tabular-nums mt-1">
            {monthlyEstimate !== null ? formatCost(monthlyEstimate) : "—"}
          </div>
          <div className="text-[11px] text-blue-300 mt-1">
            {lang === "en"
              ? "Linear extrapolation from current rate"
              : "현재 속도로 단순 외삽"}
          </div>
        </div>
      </div>

      {/* Channel comparison */}
      <section aria-labelledby="cost-channels-title" className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 space-y-3">
        <h2 id="cost-channels-title" className="text-sm font-semibold text-gray-200">
          {lang === "en" ? "Channel comparison" : "채널별 비교"}
        </h2>
        <DataError
          error={channelsResource.error}
          resource={lang === "en" ? "channel comparison" : "채널별 비교"}
          onRetry={() => { reset(); void channelsResource.refresh(); }}
          hasData={channels !== null}
        />
        {channelsResource.loading && <DataLoading />}
        {!channelsResource.error && !channelsResource.refreshing && channels?.channels.length === 0 && <DataEmpty />}
        {channels && channels.channels.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
            {channels.channels.map((c) => (
              <div
                key={c.channel}
                className={`rounded-lg border p-3 ${CHANNEL_COLORS[c.channel] ?? "bg-gray-800 border-gray-700 text-gray-300"}`}
              >
                <div className="text-xs font-semibold">{c.channel}</div>
                <div className="text-xl font-bold tabular-nums mt-1">{formatCost(c.cost_usd)}</div>
                <div className="text-[11px] mt-1 space-y-0.5">
                  <div>{c.samples.toLocaleString()} {lang === "en" ? "calls" : "호출"}</div>
                  <div>
                    {c.input_tokens.toLocaleString()} in / {c.output_tokens.toLocaleString()} out
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Per-model breakdown */}
      <section aria-labelledby="cost-models-title" className="min-w-0 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
        <h2 id="cost-models-title" className="text-sm font-semibold text-gray-200 mb-3">
          {lang === "en" ? "Per-model breakdown" : "모델별 상세"}
        </h2>
        {summaryResource.loading && <DataLoading />}
        {!summaryResource.error && !summaryResource.refreshing && summary?.rows.length === 0 && <DataEmpty />}
        {summary && summary.rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-800">
                  <th className="text-left py-2 pr-3">{lang === "en" ? "Model" : "모델"}</th>
                  <th className="text-left py-2 px-2">{lang === "en" ? "Channel" : "채널"}</th>
                  <th className="text-right py-2 px-2">{lang === "en" ? "Calls" : "호출"}</th>
                  <th className="text-right py-2 px-2">{lang === "en" ? "In tok" : "입력 토큰"}</th>
                  <th className="text-right py-2 px-2">{lang === "en" ? "Out tok" : "출력 토큰"}</th>
                  <th className="text-right py-2 px-2">{lang === "en" ? "Avg / call" : "호출당 평균"}</th>
                  <th className="text-right py-2 pl-2">{lang === "en" ? "Total" : "총 비용"}</th>
                </tr>
              </thead>
              <tbody>
                {summary.rows.map((r) => (
                  <tr key={r.model_id} className="border-b border-gray-800/50">
                    <td className="py-2 pr-3 text-gray-200" title={r.model_id}>
                      {r.model_name}
                    </td>
                    <td className="py-2 px-2">
                      <span className={`px-1.5 py-0.5 rounded text-[11px] border ${CHANNEL_COLORS[r.channel] ?? ""}`}>
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
          </div>
        )}
        <p className="text-[11px] text-gray-500 mt-2">
          {lang === "en"
            ? "Cost is calculated from "
            : "비용은 공식 출처에서 12시간마다 갱신하는 "}
          <Link href="/pricing" className="text-blue-400 hover:underline">{lang === "en" ? "Unit Prices" : "비용 단가"}</Link>
          {lang === "en"
            ? ", refreshed from official sources every 12 hours, and excludes failed and overloaded calls."
            : "로 계산하며, 실패와 과부하 호출은 제외합니다."}
        </p>
      </section>

      {/* 비용 산정 방법 설명 박스 */}
      <div className="bg-gray-900/40 border border-gray-800/60 rounded-xl p-5 space-y-2 text-xs text-gray-400 break-words">
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
        <p data-cost-methodology>
          {lang === "en"
            ? "Token counts come from each model's response usage object (per call). Unit prices are refreshed from official sources every 12 hours, and each probe is costed at the price in effect at its time. See "
            : "토큰 수는 모델 응답의 usage 객체에서 호출별로 수집합니다. 단가는 공식 출처에서 12시간마다 자동 갱신되고, 비용은 각 프로브 시각의 단가로 계산합니다. 모델별 단가와 출처는 "}
          <Link href="/pricing" className="text-blue-400 hover:underline">{lang === "en" ? "Unit Prices" : "비용 단가"}</Link>
          {lang === "en" ? " for per-model prices and sources." : " 메뉴를 참고하세요."}
        </p>
        <p>
          <span className="text-gray-300 font-semibold">
            {lang === "en" ? "Channel comparison" : "채널 비교"}:
          </span>{" "}
          {lang === "en"
            ? "Bedrock Global / US use cross-region inference profiles; Anthropic (CP on AWS) uses the vendor's external endpoint (aws-external-anthropic.*.api.aws). See "
            : "Bedrock Global / US는 cross-region inference profile, Anthropic CP on AWS는 vendor external endpoint(aws-external-anthropic.*.api.aws)를 사용합니다. 채널별 단가는 "}
          <Link href="/pricing" className="text-blue-400 hover:underline">{lang === "en" ? "Unit Prices" : "비용 단가"}</Link>
          {lang === "en" ? " for per-channel prices." : " 메뉴를 참고하세요."}
        </p>
        <p>
          <span className="text-gray-300 font-semibold">
            {lang === "en" ? "30-day projection" : "30일 예상"}:
          </span>{" "}
          {lang === "en"
            ? "linear extrapolation — total_cost_in_window ÷ window_hours × 24 × 30. Useful as a rough budget signal but does not account for variable workload or pricing changes."
            : "선택한 기간 비용을 시간당으로 환산해 × 24 × 30으로 단순 외삽. 워크로드 변동, 단가 변경은 반영되지 않은 대략적 budget 신호입니다."}
        </p>
        <p>
          {lang === "en"
            ? "Excluded from cost: failed and overloaded calls (we still charge nothing for these, but they wouldn't reflect actual application spend). Cost is built from successful invocations only."
            : "실패와 과부하(overloaded) 호출은 비용 집계에서 제외하고 성공 호출만 합산합니다."}
        </p>
      </div>
    </div>
  );
}
