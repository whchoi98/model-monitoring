"use client";

// GPT on AWS (v2.18.0) — Bedrock Mantle 3P의 GPT 5.4 / 5.5 / 5.6 Terra 8채널을
// 15분마다 채널당 10회 정밀 측정(TTFB/TTFT/GAP)한 결과의 스코어 카드 + 시계열.
// 방법론은 docs/benchmarks (ttft_bench) 계보: TTFB=첫 스트림 이벤트, GAP≈thinking.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";
import {
  fetchGptBenchLatest, fetchGptBenchTrend,
  GptBenchLatest, GptBenchTrend,
} from "@/lib/api";
import { useLang } from "@/lib/i18n-context";
import { useChartTheme } from "@/lib/chartTheme";

const RANGE_OPTIONS = [
  { hours: 3, labelKo: "3시간", labelEn: "3h" },
  { hours: 6, labelKo: "6시간", labelEn: "6h" },
  { hours: 12, labelKo: "12시간", labelEn: "12h" },
  { hours: 24, labelKo: "24시간", labelEn: "24h" },
  { hours: 72, labelKo: "3일", labelEn: "3d" },
  { hours: 168, labelKo: "7일", labelEn: "7d" },
];

// 이중 인코딩으로 8개 라인 구분: 색 = 리전, 선 패턴 = 모델 family.
// (초기 버전의 초록 8단계는 구분 불가 피드백 → 리전 3색 × family 3패턴으로 교체)
const REGION_COLORS: Record<string, string> = {
  "us-east-1": "#3b82f6", // blue
  "us-east-2": "#f59e0b", // amber
  "us-west-2": "#10b981", // emerald
};

const FAMILY_DASH: Record<string, string | undefined> = {
  "GPT 5.6 Terra": undefined, // 실선
  "GPT 5.5": "7 4",           // 파선
  "GPT 5.4": "2 4",           // 점선
};

function regionOf(name: string): string {
  const m = name.match(/\((us-[a-z]+-\d)\)/);
  return m ? m[1] : "";
}

function familyOf(name: string): string {
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
  if (v === null || v === undefined) return "-";
  return v >= 10000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
}

/** series[] → recharts rows: [{ ts, "<model_name>": value }] */
function toChartData(
  trend: GptBenchTrend | null,
  metric: "median_ttfb_ms" | "median_ttft_ms" | "median_gap_ms",
): { rows: Record<string, number | string | null>[]; names: string[] } {
  if (!trend) return { rows: [], names: [] };
  const byTs: Record<string, Record<string, number | string | null>> = {};
  const names: string[] = [];
  for (const s of trend.series) {
    names.push(s.model_name);
    for (const p of s.points) {
      const key = p.cycle_ts;
      byTs[key] = byTs[key] || { ts: key };
      byTs[key][s.model_name] = p[metric];
    }
  }
  const rows = Object.values(byTs).sort((a, b) =>
    String(a.ts).localeCompare(String(b.ts)));
  return { rows, names };
}

function BenchChart({
  trend, metric, title, selected,
}: {
  trend: GptBenchTrend | null;
  metric: "median_ttfb_ms" | "median_ttft_ms" | "median_gap_ms";
  title: string;
  selected: Set<string>;
}) {
  const ct = useChartTheme();
  // 대시보드와 동일 규칙: 빈 선택 = 전체 표시.
  const filtered = useMemo(() => {
    if (!trend || selected.size === 0) return trend;
    return { ...trend, series: trend.series.filter((s) => selected.has(s.model_name)) };
  }, [trend, selected]);
  const { rows, names } = useMemo(() => toChartData(filtered, metric), [filtered, metric]);

  const fmtTick = (ts: string) => {
    const d = new Date(ts);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };

  return (
    <div className="bg-gray-900/50 light:bg-white border border-gray-800 rounded-xl p-4">
      <h3 className="text-sm font-semibold text-gray-300 mb-3">{title}</h3>
      {rows.length === 0 ? (
        <div className="h-56 flex items-center justify-center text-sm text-gray-500">-</div>
      ) : (
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={rows} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={ct.grid} strokeDasharray="3 3" />
            <XAxis dataKey="ts" tickFormatter={fmtTick} tick={{ fontSize: 11, fill: ct.tick }}
                   stroke={ct.axisLine} minTickGap={40} />
            <YAxis tick={{ fontSize: 11, fill: ct.tick }} stroke={ct.axisLine}
                   tickFormatter={(v: number) => (v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${v}`)} width={52} />
            <Tooltip contentStyle={ct.tooltipStyle} labelStyle={ct.tooltipLabel}
                     labelFormatter={(ts) => new Date(String(ts)).toLocaleString()}
                     formatter={(v: number | string, name: string) => [fmtMs(Number(v)), name]} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {names.map((n) => (
              <Line key={n} type="monotone" dataKey={n} stroke={color(n)} dot={false}
                    strokeWidth={1.8} strokeDasharray={dash(n)} connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}

export default function GptOnAwsPanel() {
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const [hours, setHours] = useState(24);
  const [latest, setLatest] = useState<GptBenchLatest | null>(null);
  const [trend, setTrend] = useState<GptBenchTrend | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
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

  const load = useCallback(async () => {
    setError(null);
    try {
      const [l, t] = await Promise.all([fetchGptBenchLatest(), fetchGptBenchTrend(hours)]);
      setLatest(l);
      setTrend(t);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [hours]);

  useEffect(() => { setLoading(true); load(); }, [load]);
  // 15분 주기 수집이므로 60초 자동 갱신이면 충분.
  useEffect(() => {
    const id = setInterval(load, 60000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">GPT on AWS</h1>
          <p className="text-sm text-gray-500 mt-1">
            {L(
              "Bedrock Mantle (3P) precision latency bench — GPT 5.4 / 5.5 / 5.6 Terra × 3 US regions, 10 sequential calls per channel every 15 minutes with a fixed ~55.8k-token cached prompt. TTFB = first stream event, GAP ≈ server-side thinking.",
              "Bedrock Mantle(3P) 정밀 레이턴시 벤치 — GPT 5.4 / 5.5 / 5.6 Terra × 미국 3리전을 15분마다 채널당 10회 순차 호출 (~55.8k 토큰 고정 캐시 프롬프트). TTFB = 첫 스트림 이벤트, GAP ≈ 서버측 thinking 시간.",
            )}
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="text-xs text-gray-400">{L("Range", "기간")}</span>
          <div className="flex gap-1">
            {RANGE_OPTIONS.map((r) => (
              <button
                key={r.hours}
                onClick={() => setHours(r.hours)}
                className={`px-2.5 py-1 text-xs rounded-md ${hours === r.hours ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700"}`}
              >
                {lang === "en" ? r.labelEn : r.labelKo}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-rose-800/50 bg-rose-950/40 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-16">
          <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {!loading && latest && latest.channels.length === 0 && (
        <div className="text-center py-16 text-gray-500 text-sm">
          {L("No bench data yet — the first 15-minute cycle has not completed.",
             "아직 벤치 데이터가 없습니다 — 첫 15분 사이클이 완료되면 표시됩니다.")}
        </div>
      )}

      {/* 스코어 카드 */}
      {!loading && latest && latest.channels.length > 0 && (
        <>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2 text-xs text-gray-500">
              <span>{L("Latest cycle", "최신 사이클")}:</span>
              <span className="font-mono">
                {latest.cycle_ts ? new Date(latest.cycle_ts).toLocaleString() : "-"}
              </span>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-gray-500">
                {L("Click cards to filter charts", "카드를 클릭하면 그래프 채널이 선택됩니다")}
              </span>
              <button
                onClick={clearChannels}
                className={`px-2.5 py-1 rounded-full border transition-colors ${
                  selectedChannels.size === 0
                    ? "bg-blue-600 border-blue-600 text-white"
                    : "bg-gray-800 border-gray-700 text-gray-400 hover:text-gray-200"
                }`}
              >
                {L("All", "전체")}
              </button>
              {selectedChannels.size > 0 && (
                <span className="text-gray-500">{selectedChannels.size}/{latest.channels.length}</span>
              )}
            </div>
          </div>
          {/* family별 열 배치: 1열 GPT 5.6 Terra · 2열 GPT 5.5 · 3열 GPT 5.4 (모바일은 세로 스택) */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {(["GPT 5.6 Terra", "GPT 5.5", "GPT 5.4"] as const).map((fam) => (
              <div key={fam} className="space-y-3">
                <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-500 px-1">
                  {fam}
                </h3>
                {latest.channels.filter((c) => c.family === fam).map((c) => (
              <button key={c.model_id} type="button"
                   onClick={() => toggleChannel(c.model_name)}
                   className={`text-left rounded-xl border p-4 space-y-2 transition-colors bg-gray-900/50 light:bg-white ${
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
                  <span className="text-[10px] font-mono text-gray-500">{c.region}</span>
                </div>
                <div className="grid grid-cols-3 gap-1 text-center">
                  <div>
                    <div className={`text-lg font-bold tabular-nums ${ttfbColor(c.median_ttfb_ms)}`}>
                      {fmtMs(c.median_ttfb_ms)}
                    </div>
                    <div className="text-[10px] text-gray-500">TTFB</div>
                  </div>
                  <div>
                    <div className={`text-lg font-bold tabular-nums ${ttftColor(c.median_ttft_ms)}`}>
                      {fmtMs(c.median_ttft_ms)}
                    </div>
                    <div className="text-[10px] text-gray-500">TTFT</div>
                  </div>
                  <div>
                    <div className="text-lg font-bold tabular-nums text-gray-300">
                      {fmtMs(c.median_gap_ms)}
                    </div>
                    <div className="text-[10px] text-gray-500">GAP</div>
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
                    {c.cache_hit_rate !== null ? `${Math.round(c.cache_hit_rate * 100)}%` : "-"}
                  </span>
                </div>
                {c.last_error && (
                  <div className="text-[10px] text-rose-400/90 truncate" title={c.last_error}>
                    {c.last_error}
                  </div>
                )}
              </button>
                ))}
              </div>
            ))}
          </div>

          {/* 시계열 그래프 */}
          <div className="grid grid-cols-1 gap-4">
            <BenchChart trend={trend} metric="median_ttfb_ms" selected={selectedChannels}
                        title={L("TTFB trend (median per cycle)", "TTFB 추이 (사이클 median)")} />
            <BenchChart trend={trend} metric="median_ttft_ms" selected={selectedChannels}
                        title={L("TTFT trend (median per cycle)", "TTFT 추이 (사이클 median)")} />
            <BenchChart trend={trend} metric="median_gap_ms" selected={selectedChannels}
                        title={L("GAP (thinking) trend", "GAP(thinking) 추이")} />
          </div>
        </>
      )}
    </div>
  );
}
