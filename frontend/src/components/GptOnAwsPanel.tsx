"use client";

// GPT on AWS (v2.18.0) — Bedrock Mantle 3P의 GPT 5.4 / 5.5 / 5.6 Terra / 6 Astra 12채널
// (미국 3리전 + Terra Global CRIS v2.20.1 + Astra Global·US CRIS·us-west-2 v2.25.1)을
// 15분마다 채널당 10회 정밀 측정(TTFB/TTFT/GAP)한 결과의 스코어 카드 + 시계열.
// 방법론은 docs/benchmarks (ttft_bench) 계보: TTFB=첫 스트림 이벤트, GAP≈thinking.

import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer,
} from "recharts";
import {
  fetchGptBenchLatest, fetchGptBenchTrend,
  GptBenchLatest, GptBenchTrend,
} from "@/lib/api";
import { useLang, useT } from "@/lib/i18n-context";
import { useChartTheme } from "@/lib/chartTheme";
import { formatAge, formatDateTime, parseTimestamp } from "@/lib/format";
import { isolatedSampleTimes } from "@/lib/pivotTrend";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { DataEmpty, DataError, DataLoading } from "@/components/DataState";
import RefreshControls from "@/components/RefreshControls";

// 15-minute collection cadence plus 15 minutes of grace.
const STALE_AFTER_MS = 30 * 60_000;

const RANGE_OPTIONS = [
  { hours: 3, labelKo: "3시간", labelEn: "3h" },
  { hours: 6, labelKo: "6시간", labelEn: "6h" },
  { hours: 12, labelKo: "12시간", labelEn: "12h" },
  { hours: 24, labelKo: "24시간", labelEn: "24h" },
  { hours: 72, labelKo: "3일", labelEn: "3d" },
  { hours: 168, labelKo: "7일", labelEn: "7d" },
];

// 이중 인코딩으로 12개 라인 구분: 색 = 리전, 선 패턴 = 모델 family.
// (초기 버전의 초록 8단계는 구분 불가 피드백 → 리전 색 × family 패턴으로 교체)
const REGION_COLORS: Record<string, string> = {
  "us-east-1": "#3b82f6", // blue
  "us-east-2": "#f59e0b", // amber
  "us-west-2": "#10b981", // emerald
  "Global": "#a855f7",    // violet — Global CRIS (Seoul 라우팅, v2.20.1)
  "US": "#db2777",        // pink-600 — US CRIS (us-east-1 라우팅, v2.25.1)
};

const FAMILY_DASH: Record<string, string | undefined> = {
  "GPT 6 Astra": "10 3 2 3",  // 일점쇄선
  "GPT 5.6 Terra": undefined, // 실선
  "GPT 5.5": "7 4",           // 파선
  "GPT 5.4": "2 4",           // 점선
};

/** model_name 서픽스 → 리전 키. pseudo-region "(US)"(v2.25.1)는 "(us-west-2)"와 구분된다. */
export function regionOf(name: string): string {
  const m = name.match(/\((us-[a-z]+-\d|Global|US)\)/);
  return m ? m[1] : "";
}

/** model_name → family 키. "6 Astra"를 먼저 보지 않으면 5.4로 접힌다(기본값이 5.4). */
export function familyOf(name: string): string {
  if (name.includes("6 Astra")) return "GPT 6 Astra";
  if (name.includes("5.6 Terra")) return "GPT 5.6 Terra";
  if (name.includes("5.5")) return "GPT 5.5";
  return "GPT 5.4";
}

function color(name: string): string {
  return REGION_COLORS[regionOf(name)] || "#9ca3af";
}

function dash(name: string): string | undefined {
  return FAMILY_DASH[familyOf(name)];
}

function ttfbColor(ms: number | null): string {
  if (ms === null) return "text-gray-500";
  if (ms < 1200) return "text-emerald-400";
  if (ms < 2500) return "text-amber-400";
  return "text-rose-400";
}

function ttftColor(ms: number | null): string {
  if (ms === null) return "text-gray-500";
  if (ms < 2500) return "text-emerald-400";
  if (ms < 5000) return "text-amber-400";
  return "text-rose-400";
}

function fmtMs(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v >= 10000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
}

type ChartRow = { ts: number; [name: string]: number | null };

/**
 * backend/gptbench.py run_cycle() assigns one cycle_ts to every channel.
 * Keep that shared timeline, including cycles missing from a selected channel.
 * The trend API's medians include successful calls only; null means unmeasured,
 * while an errors count can coexist with a valid median from a partial success.
 */
export function toChartData(
  trend: GptBenchTrend,
  metric: "median_ttfb_ms" | "median_ttft_ms" | "median_gap_ms",
): { rows: ChartRow[]; names: string[] } {
  const byTs = new Map<number, ChartRow>();
  const names = Array.from(new Set(trend.series.map((series) => series.model_name)));
  for (const s of trend.series) {
    for (const p of s.points) {
      const ts = parseTimestamp(p.cycle_ts);
      if (ts === null) continue;
      const row: ChartRow = byTs.get(ts) ?? { ts };
      if (!byTs.has(ts)) {
        for (const name of names) row[name] = null;
        byTs.set(ts, row);
      }
      const value = p[metric];
      row[s.model_name] = typeof value === "number" && Number.isFinite(value) ? value : null;
    }
  }
  const cycles = Array.from(byTs.values()).sort((a, b) => a.ts - b.ts);
  const rows: ChartRow[] = [];
  for (const cycle of cycles) {
    const previous = rows[rows.length - 1];
    if (previous && cycle.ts - previous.ts > STALE_AFTER_MS) {
      // A separator marks a collector outage; it is not a measured cycle.
      const gap: ChartRow = { ts: previous.ts + (cycle.ts - previous.ts) / 2 };
      for (const name of names) gap[name] = null;
      rows.push(gap);
    }
    rows.push(cycle);
  }
  return { rows, names };
}

function BenchChart({
  trend, metric, title, selected,
}: {
  trend: GptBenchTrend;
  metric: "median_ttfb_ms" | "median_ttft_ms" | "median_gap_ms";
  title: string;
  selected: Set<string>;
}) {
  const ct = useChartTheme();
  const { lang } = useLang();
  const t = useT();
  const { rows, names: allNames } = useMemo(() => toChartData(trend, metric), [trend, metric]);
  // Filter lines after building the timeline so a missing channel never bridges a cycle.
  const names = selected.size === 0 ? allNames : allNames.filter((name) => selected.has(name));
  const hasMeasurements = rows.some((row) => names.some((name) => typeof row[name] === "number"));
  const spansDays = rows.length > 1
    && new Date(rows[0].ts).toDateString() !== new Date(rows[rows.length - 1].ts).toDateString();
  const timeFormatter = new Intl.DateTimeFormat(lang === "ko" ? "ko-KR" : "en-US", {
    ...(spansDays ? { month: "short", day: "numeric" } as const : {}),
    hour: "2-digit", minute: "2-digit", hour12: false,
  });
  const showDots = rows.length * names.length <= 700;

  return (
    <section aria-label={title} className="min-w-0 bg-gray-900/50 border border-gray-800 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-3">{title}</h3>
      {rows.length === 0 || names.length === 0 ? (
        <DataEmpty title={t.monitoring.noTrend} description={t.common.noDataHint} />
      ) : !hasMeasurements ? (
        <DataEmpty title={t.monitoring.noMetric} description={t.monitoring.noMetricHint} />
      ) : (
        <>
          <div className="h-[260px] min-w-0">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart accessibilityLayer data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
                <CartesianGrid stroke={ct.grid} strokeDasharray="3 3" />
                <XAxis dataKey="ts" type="number" scale="time"
                       domain={rows.length === 1 ? [rows[0].ts - 450_000, rows[0].ts + 450_000] : ["dataMin", "dataMax"]}
                       tickFormatter={(ts: number) => timeFormatter.format(ts)}
                       tick={{ fontSize: 11, fill: ct.tick }} tickCount={4}
                       stroke={ct.axisLine} minTickGap={28} height={44} />
                <YAxis tick={{ fontSize: 11, fill: ct.tick }} stroke={ct.axisLine}
                       tickFormatter={(v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}ms`)} width={52} />
                <Tooltip contentStyle={ct.tooltipStyle} labelStyle={ct.tooltipLabel}
                         labelFormatter={(ts) => formatDateTime(Number(ts), lang)}
                         formatter={(value, name) => [fmtMs(typeof value === "number" ? value : null), name]} />
                {names.map((name) => {
                  const isolated = isolatedSampleTimes(rows, name, "ts");
                  const stroke = color(name);
                  return (
                    <Line key={name} type="linear" dataKey={name} stroke={stroke}
                          strokeWidth={1.8} strokeDasharray={dash(name)} connectNulls={false}
                          isAnimationActive={false} activeDot={{ r: 4 }}
                          dot={({ key, cx, cy, payload }: {
                            key?: string; cx?: number; cy?: number; payload?: ChartRow;
                          }) =>
                            payload && typeof payload[name] === "number" && (showDots || isolated.has(payload.ts))
                              && Number.isFinite(cx) && Number.isFinite(cy)
                              ? <circle key={key} className="recharts-line-dot" cx={cx} cy={cy} r={2.5} fill={stroke} />
                              : <Fragment key={key} />} />
                  );
                })}
              </LineChart>
            </ResponsiveContainer>
          </div>
          <ul aria-label={lang === "en" ? "Chart legend" : "차트 범례"} tabIndex={0}
              className="mt-3 flex max-h-36 flex-wrap gap-x-4 gap-y-2 overflow-y-auto rounded-md p-1 text-[11px] text-gray-400">
            {names.map((name) => (
              <li key={name} className="flex min-w-0 items-center gap-2">
                <svg aria-hidden="true" width="28" height="8" viewBox="0 0 28 8" className="shrink-0">
                  <line x1="1" y1="4" x2="27" y2="4" stroke={color(name)} strokeWidth="2" strokeDasharray={dash(name)} />
                </svg>
                <span className="break-words">{name}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

export default function GptOnAwsPanel() {
  const { lang } = useLang();
  const t = useT();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const [hours, setHours] = useState(24);
  const latestResource = useAsyncResource<GptBenchLatest>("gptbench-latest", fetchGptBenchLatest);
  const trendResource = useAsyncResource<GptBenchTrend>(`gptbench-trend:${hours}`, (signal) => fetchGptBenchTrend(hours, signal));
  const { data: latest, refresh: refreshLatest } = latestResource;
  const { data: trend, refresh: refreshTrend } = trendResource;
  const refresh = useCallback(async () => {
    await Promise.all([refreshLatest(), refreshTrend()]);
  }, [refreshLatest, refreshTrend]);
  const autoRefresh = useAutoRefresh(refresh, 60_000);
  const [now, setNow] = useState(() => Date.now());

  // Collection age keeps advancing even when automatic network refresh is paused.
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  const cycleTime = parseTimestamp(latest?.cycle_ts);
  const stale = cycleTime !== null && now - cycleTime > STALE_AFTER_MS;
  // 대시보드 카드 필터와 동일 규칙: 빈 Set = 전체. 카드 클릭으로 토글.
  const [selectedChannels, setSelectedChannels] = useState<Set<string>>(new Set());
  const toggleChannel = (name: string) => {
    setSelectedChannels((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };
  const clearChannels = () => setSelectedChannels(new Set());

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">GPT on AWS</h1>
          <p className="text-sm text-gray-500 mt-1">
            {L(
              "Precision latency measurements for GPT 5.4, 5.5, 5.6 Terra and 6 Astra on Bedrock Mantle and cross-region channels. Each 15-minute cycle makes 10 sequential calls per channel with a fixed ~55.8k-token cached prompt. TTFB = first stream event, GAP ≈ server-side thinking.",
              "Bedrock Mantle 및 교차 리전 채널의 GPT 5.4, 5.5, 5.6 Terra, 6 Astra 정밀 레이턴시 측정입니다. 15분마다 채널당 10회 순차 호출하며, 약 55.8k 토큰의 고정 캐시 프롬프트를 사용합니다. TTFB = 첫 스트림 이벤트, GAP ≈ 서버측 thinking 시간.",
            )}
          </p>
        </div>
        <RefreshControls refreshing={latestResource.refreshing || trendResource.refreshing}
                         onRefresh={() => { autoRefresh.reset(); void refresh(); }}
                         updatedAt={latestResource.updatedAt} enabled={autoRefresh.enabled}
                         onEnabledChange={autoRefresh.setEnabled} countdown={autoRefresh.countdown} />
      </div>

      <section aria-label={L("Benchmark cards", "벤치마크 카드")} className="space-y-4">
        <DataError error={latestResource.error} resource={L("benchmark cards", "벤치마크 카드")}
                   onRetry={refreshLatest} hasData={!!latest?.channels.length} />
        {latestResource.loading && <DataLoading label={L("Loading benchmark cards…", "벤치마크 카드를 불러오는 중…")} />}

        {!latestResource.error && latest && latest.channels.length === 0 && (
          <DataEmpty title={L("No benchmark data yet.", "아직 벤치마크 데이터가 없습니다.")}
                     description={L("Results appear after the first collection cycle. Collection runs every 15 minutes.",
                                    "첫 수집 사이클이 완료되면 결과가 표시됩니다. 수집은 15분마다 실행됩니다.")} />
        )}

      {/* 스코어 카드 */}
      {latest && latest.channels.length > 0 && (
        <>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
              <span>{L("Collection cycle started", "수집 사이클 시작")}:</span>
              <time className="tabular-nums text-gray-400" dateTime={cycleTime === null ? undefined : new Date(cycleTime).toISOString()}>
                {formatDateTime(cycleTime, lang)}
              </time>
              {cycleTime !== null && <span>({formatAge(cycleTime, lang, now)})</span>}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <span className="text-gray-500">
                {L("Click cards to filter charts", "카드를 클릭하면 그래프 채널이 선택됩니다")}
              </span>
              <button
                type="button"
                onClick={clearChannels}
                aria-pressed={selectedChannels.size === 0}
                className={selectedChannels.size === 0 ? "ui-button-primary" : "ui-button"}
              >
                {L("All", "전체")}
              </button>
              {selectedChannels.size > 0 && (
                <span className="text-gray-500">{selectedChannels.size}/{latest.channels.length}</span>
              )}
            </div>
          </div>
          {stale && (
            <div role="status" className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
              <p className="text-sm font-medium text-amber-300">{L("Collection delayed", "수집 지연")}</p>
              <p className="mt-1 text-xs leading-relaxed text-gray-400">
                {L("The latest collection cycle started over 30 minutes ago. Cycles normally run every 15 minutes; refreshing checks for stored results.",
                   "최신 수집 사이클이 시작된 지 30분이 넘었습니다. 수집은 보통 15분마다 실행되며, 새로고침은 저장된 결과를 다시 확인합니다.")}
              </p>
            </div>
          )}
          {/* family별 열 배치: 1열 GPT 6 Astra, 2열 GPT 5.6 Terra, 3열 GPT 5.5, 4열 GPT 5.4
              (폰은 세로 스택, md 2열, xl 4열) */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {(["GPT 6 Astra", "GPT 5.6 Terra", "GPT 5.5", "GPT 5.4"] as const).map((fam) => (
              <div key={fam} className="min-w-0 space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 px-1">
                  {fam}
                </h3>
                {latest.channels.filter((c) => c.family === fam).map((c) => (
              <button key={c.model_id} type="button"
                   onClick={() => toggleChannel(c.model_name)}
                   aria-label={c.model_name}
                   aria-pressed={selectedChannels.size === 0 || selectedChannels.has(c.model_name)}
                   className={`block w-full min-w-0 text-left rounded-xl border p-4 space-y-2 transition-colors bg-gray-900/50 focus-visible:border-blue-500 ${
                     selectedChannels.has(c.model_name)
                       ? "border-blue-500 ring-1 ring-blue-500/50"
                       : "border-gray-800 hover:border-gray-600"
                   }`}>
                <div className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: color(c.model_name) }} />
                    <span className="text-sm font-semibold text-gray-200 truncate">
                      {c.family}
                    </span>
                  </div>
                  <span className="text-[11px] font-mono text-gray-500">{c.region}</span>
                </div>
                <div className="grid grid-cols-3 gap-1 text-center">
                  <div>
                    <div className={`text-lg font-bold tabular-nums ${ttfbColor(c.median_ttfb_ms)}`}>
                      {fmtMs(c.median_ttfb_ms)}
                    </div>
                    <div className="text-[11px] text-gray-500">TTFB</div>
                  </div>
                  <div>
                    <div className={`text-lg font-bold tabular-nums ${ttftColor(c.median_ttft_ms)}`}>
                      {fmtMs(c.median_ttft_ms)}
                    </div>
                    <div className="text-[11px] text-gray-500">TTFT</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold tabular-nums text-gray-300">
                      {fmtMs(c.median_gap_ms)}
                    </div>
                    <div className="text-[11px] text-gray-500">GAP</div>
                  </div>
                </div>
                <div className="flex items-center justify-between text-[11px] text-gray-500 pt-1 border-t border-gray-800/60">
                  <span>
                    {L("ok", "성공")} {c.success}/{c.runs}
                    {c.success < c.runs && <span className="text-rose-400"> ⚠</span>}
                  </span>
                  <span>p95 {fmtMs(c.p95_ttft_ms)}</span>
                  <span>
                    {L("cache", "캐시")}{" "}
                    {c.cache_hit_rate !== null ? `${Math.round(c.cache_hit_rate * 100)}%` : "—"}
                  </span>
                </div>
                {c.last_error && (
                  <div className="text-[11px] text-rose-400 break-words">
                    {c.last_error}
                  </div>
                )}
              </button>
                ))}
              </div>
            ))}
          </div>

        </>
      )}
      </section>

      <section aria-label={L("Benchmark trends", "벤치마크 추세")} className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-gray-200">{L("Benchmark trends", "벤치마크 추세")}</h2>
          <div role="group" aria-label={L("Time range", "조회 기간")} className="flex flex-wrap items-center gap-1">
            <span className="mr-2 text-xs text-gray-400">{L("Range", "기간")}</span>
            {RANGE_OPTIONS.map((range) => (
              <button key={range.hours} type="button" onClick={() => setHours(range.hours)}
                      aria-pressed={hours === range.hours}
                      className={hours === range.hours ? "ui-button-primary" : "ui-button"}>
                {lang === "en" ? range.labelEn : range.labelKo}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-gray-500">{t.monitoring.trendHint}</p>
        <DataError error={trendResource.error} resource={L("benchmark trends", "벤치마크 추세")}
                   onRetry={refreshTrend} hasData={!!trend?.series.some((series) => series.points.length > 0)} />
        {trendResource.loading && <DataLoading label={L("Loading benchmark trends…", "벤치마크 추세를 불러오는 중…")} />}
        {!trendResource.error && trend && !trend.series.some((series) => series.points.length > 0) && (
          <DataEmpty title={t.monitoring.noTrend} description={t.monitoring.noTrendHint} />
        )}
        {trend && trend.series.some((series) => series.points.length > 0) && (
          <div className="grid grid-cols-1 gap-4">
            <BenchChart trend={trend} metric="median_ttfb_ms" selected={selectedChannels}
                        title={L("TTFB trend (median per cycle)", "TTFB 추이 (사이클 median)")} />
            <BenchChart trend={trend} metric="median_ttft_ms" selected={selectedChannels}
                        title={L("TTFT trend (median per cycle)", "TTFT 추이 (사이클 median)")} />
            <BenchChart trend={trend} metric="median_gap_ms" selected={selectedChannels}
                        title={L("GAP (thinking) trend", "GAP(thinking) 추이")} />
          </div>
        )}
      </section>
    </div>
  );
}
