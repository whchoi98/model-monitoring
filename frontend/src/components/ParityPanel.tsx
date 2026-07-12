"use client";

// 패리티 런 (v2.11.0) — 실제 API 호출 증거 기반의 기능 패리티 매트릭스.
// 모든 셀은 실행-증거 프로브의 판정 결과 (supported/unsupported/broken/skipped).
// 셀 클릭 → 해당 프로브의 요청 요약·응답 스니펫·오류 등 증거 표시.

import { Fragment, useEffect, useMemo, useState } from "react";
import { useLang } from "@/lib/i18n-context";
import { getToken } from "@/lib/api";

const BASE = "";

type Status = "supported" | "unsupported" | "broken" | "skipped";

interface ParityCell {
  model_id: string;
  model_name: string;
  surface: string;
  feature: string;
  status: Status;
  latency_ms: number | null;
}

interface ParityRunInfo {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  totals: Record<string, number> | null;
  running: boolean;
}

interface Feature {
  id: string;
  label_ko: string;
  desc_ko: string;
}

interface ParityChange {
  model_id: string;
  model_name: string;
  surface: string;
  feature: string;
  before: Status | null;
  after: Status;
}

const SURFACE_LABELS: Record<string, string> = {
  converse: "Converse",
  invoke_model: "InvokeModel",
  messages: "Messages",
  messages_mantle: "Messages (Mantle)",
  chat_completions: "ChatCompletions",
  responses: "Responses",
};

const STATUS_STYLE: Record<Status, string> = {
  supported: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  unsupported: "bg-amber-500/10 border-amber-500/30 text-amber-300",
  broken: "bg-rose-500/10 border-rose-500/30 text-rose-300",
  skipped: "bg-gray-800 border-gray-700 text-gray-500",
};

const STATUS_LABEL: Record<Status, string> = {
  supported: "Supported",
  unsupported: "Unsupported",
  broken: "Broken",
  skipped: "—",
};

// provider 그룹 — 상단 요약 카드 + 우측 상세 바 단위
function providerOf(modelId: string): string {
  if (modelId.startsWith("openai:")) return "OpenAI";
  if (modelId.includes("nova")) return "Amazon";
  return "Anthropic";
}

interface ProviderStat {
  provider: string;
  counts: Record<Status, number>;
  total: number;
  health: number; // supported / (supported + broken)
}

const DONUT_COLORS: Record<Status, string> = {
  supported: "#34d399",
  unsupported: "#fbbf24",
  broken: "#fb7185",
  skipped: "#4b5563",
};

function Donut({ counts, health }: { counts: Record<Status, number>; health: number }) {
  const total = Math.max(1, (Object.values(counts) as number[]).reduce((a, b) => a + b, 0));
  const R = 34;
  const C = 2 * Math.PI * R;
  let offset = 0;
  const order: Status[] = ["supported", "unsupported", "broken", "skipped"];
  return (
    <svg viewBox="0 0 88 88" className="w-24 h-24 shrink-0" role="img" aria-label={`healthy ${health}%`}>
      {order.map((s) => {
        const frac = (counts[s] ?? 0) / total;
        const seg = (
          <circle
            key={s}
            cx="44" cy="44" r={R} fill="none"
            stroke={DONUT_COLORS[s]} strokeWidth="9"
            strokeDasharray={`${frac * C} ${C}`}
            strokeDashoffset={-offset * C}
            transform="rotate(-90 44 44)"
          />
        );
        offset += frac;
        return seg;
      })}
      <text x="44" y="42" textAnchor="middle" className="fill-gray-100" fontSize="17" fontWeight="700">{health}%</text>
      <text x="44" y="56" textAnchor="middle" className="fill-gray-500" fontSize="8" letterSpacing="1">HEALTHY</text>
    </svg>
  );
}

function ProviderDrawer({
  provider, cells, features, lang, onClose,
}: {
  provider: string;
  cells: ParityCell[];
  features: Feature[];
  lang: string;
  onClose: () => void;
}) {
  const featureLabel = (id: string) =>
    lang === "en" ? id : features.find((f) => f.id === id)?.label_ko ?? id;

  // Broken — 피처별 그룹: 실패 채널 수 / 검사 채널 수 + 대상 모델·surface
  const brokenByFeature = useMemo(() => {
    const byFeature = new Map<string, { broken: ParityCell[]; probed: number }>();
    for (const c of cells) {
      if (c.status === "skipped") continue;
      const g = byFeature.get(c.feature) ?? { broken: [], probed: 0 };
      g.probed += 1;
      if (c.status === "broken") g.broken.push(c);
      byFeature.set(c.feature, g);
    }
    return Array.from(byFeature.entries())
      .filter(([, g]) => g.broken.length > 0)
      .sort((a, b) => b[1].broken.length - a[1].broken.length);
  }, [cells]);

  // 깨끗한 미지원 — (feature, surface) 고유 조합 칩
  const unsupportedChips = useMemo(() => {
    const set = new Map<string, { feature: string; surface: string }>();
    for (const c of cells) {
      if (c.status === "unsupported") set.set(`${c.feature}|${c.surface}`, { feature: c.feature, surface: c.surface });
    }
    return Array.from(set.values());
  }, [cells]);

  // 취약 모델 — 헬스 낮은 순 (broken 있는 모델만)
  const weakest = useMemo(() => {
    const per = new Map<string, { supported: number; broken: number }>();
    for (const c of cells) {
      if (c.status !== "supported" && c.status !== "broken") continue;
      const m = per.get(c.model_name) ?? { supported: 0, broken: 0 };
      m[c.status] += 1;
      per.set(c.model_name, m);
    }
    return Array.from(per.entries())
      .map(([name, m]) => ({ name, broken: m.broken, health: Math.round((100 * m.supported) / Math.max(1, m.supported + m.broken)) }))
      .filter((m) => m.broken > 0)
      .sort((a, b) => a.health - b.health)
      .slice(0, 5);
  }, [cells]);

  return (
    <div className="fixed inset-0 z-50">
      <button type="button" aria-label="overlay" onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <aside className="absolute right-0 top-0 h-full w-full max-w-md overflow-y-auto bg-gray-900 light:bg-white border-l border-gray-800 shadow-2xl p-6 space-y-6">
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-blue-400 uppercase">Key Findings</div>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-gray-100">{provider}</h2>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-200 text-xl leading-none" aria-label="close">×</button>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            {lang === "en" ? "Latest run · computed from every probed cell" : "최근 런 기준 · 프로브된 전체 셀에서 계산"}
          </p>
        </div>

        <section>
          <h3 className="text-sm font-semibold text-rose-300 mb-1">
            {lang === "en"
              ? `Broken — expected to work but failing (${brokenByFeature.length} features)`
              : `Broken — 동작해야 하는데 실패 (${brokenByFeature.length}개 피처)`}
          </h3>
          <p className="text-[11px] text-gray-500 mb-2">
            {lang === "en"
              ? "Live probes hit an error on advertised capabilities — regressions worth chasing."
              : "실제 프로브가 오류를 만난 항목 — 추적할 가치가 있는 회귀입니다."}
          </p>
          {brokenByFeature.length === 0 && (
            <div className="text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">
              {lang === "en" ? "No broken features." : "Broken 피처가 없습니다."}
            </div>
          )}
          <div className="space-y-2">
            {brokenByFeature.map(([fid, g]) => {
              const surfaces = Array.from(new Set(g.broken.map((c) => SURFACE_LABELS[c.surface] ?? c.surface)));
              const models = Array.from(new Set(g.broken.map((c) => c.model_name)));
              return (
                <div key={fid} className="bg-rose-500/10 border border-rose-500/20 rounded-lg px-3 py-2">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-gray-100">{featureLabel(fid)}</span>
                    <span className="text-xs font-semibold text-rose-300 whitespace-nowrap">
                      {g.broken.length}/{g.probed} {lang === "en" ? "cells" : "셀"}
                    </span>
                  </div>
                  <div className="text-[11px] text-gray-400 font-mono mt-0.5">{surfaces.join(", ")}</div>
                  <div className="text-[11px] text-gray-500 mt-0.5">
                    {models.slice(0, 3).join(" · ")}{models.length > 3 ? ` ${lang === "en" ? `+${models.length - 3} more` : `외 ${models.length - 3}개`}` : ""}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        <section>
          <h3 className="text-sm font-semibold text-amber-300 mb-1">
            {lang === "en"
              ? `Cleanly unsupported (${unsupportedChips.length})`
              : `깨끗한 미지원 (${unsupportedChips.length})`}
          </h3>
          <p className="text-[11px] text-gray-500 mb-2">
            {lang === "en"
              ? "Provider rejected the capability explicitly — deliberate gaps, not bugs."
              : "provider가 명시적으로 거부한 기능 — 버그가 아닌 의도된 격차입니다."}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {unsupportedChips.map((u) => (
              <span key={`${u.feature}|${u.surface}`} className="px-2 py-0.5 text-[11px] rounded-full bg-amber-500/10 border border-amber-500/30 text-amber-300">
                {featureLabel(u.feature)} · {SURFACE_LABELS[u.surface] ?? u.surface}
              </span>
            ))}
            {unsupportedChips.length === 0 && <span className="text-xs text-gray-500">—</span>}
          </div>
        </section>

        {weakest.length > 0 && (
          <section>
            <h3 className="text-sm font-semibold text-gray-200 mb-1">{lang === "en" ? "Weakest models" : "취약 모델"}</h3>
            <p className="text-[11px] text-gray-500 mb-2">
              {lang === "en" ? "Share of should-work checks that pass, per model." : "모델별 동작해야 하는 검사의 통과 비율."}
            </p>
            <div className="space-y-1.5">
              {weakest.map((m) => (
                <div key={m.name} className="flex items-center gap-2 text-[11px]">
                  <span className="w-44 shrink-0 truncate font-mono text-gray-400">{m.name}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-gray-800 overflow-hidden">
                    <div
                      className={`h-full rounded-full ${m.health < 60 ? "bg-rose-400" : "bg-emerald-400"}`}
                      style={{ width: `${m.health}%` }}
                    />
                  </div>
                  <span className="w-20 text-right text-gray-400 tabular-nums whitespace-nowrap">{m.health}% · {m.broken} broken</span>
                </div>
              ))}
            </div>
          </section>
        )}
      </aside>
    </div>
  );
}

function EvidenceModal({ runId, cell, onClose }: { runId: number; cell: ParityCell; onClose: () => void }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const sp = new URLSearchParams({
      run_id: String(runId), model_id: cell.model_id, surface: cell.surface, feature: cell.feature,
    });
    fetch(`${BASE}/api/parity/evidence?${sp}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [runId, cell]);

  const evidence = (data?.evidence ?? {}) as Record<string, unknown>;
  const request = evidence.request as Record<string, unknown> | undefined;
  const response: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(evidence)) if (k !== "request") response[k] = v;
  const errorMsg = data?.error_message ? String(data.error_message) : null;
  const isOk = cell.status === "supported";

  const verdict = isOk
    ? "Probe succeeded — 응답 내용이 증거 검사를 통과했습니다."
    : cell.status === "unsupported"
      ? "Provider가 기능을 명시적으로 거부했습니다 (깨끗한 미지원 응답 — 버그 아님)."
      : errorMsg
        ? `Feature expected but probe failed: ${errorMsg.slice(0, 220)}${errorMsg.length > 220 ? "…" : ""}`
        : "증거 검사 실패 — 응답은 수신했지만 검증 기준(카나리/JSON/캐시 토큰 등)을 통과하지 못했습니다.";

  const Section = ({ title, json, tone }: { title: string; json: unknown; tone?: "error" }) => (
    <details open={!isOk} className="group">
      <summary className="cursor-pointer select-none text-sm text-gray-400 hover:text-gray-200 py-1">
        <span className="inline-block w-3 text-[10px] transition-transform group-open:rotate-90">▶</span> {title}
      </summary>
      <pre className={`mt-1 rounded-lg p-3 overflow-x-auto text-xs leading-relaxed border ${
        tone === "error" ? "bg-gray-950 border-rose-500/30 text-rose-300 whitespace-pre-wrap break-all" : "bg-gray-950 border-gray-800 text-gray-200"
      }`}>
        {typeof json === "string" ? json : JSON.stringify(json ?? {}, null, 2)}
      </pre>
    </details>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" aria-label="overlay" onClick={onClose} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto bg-gray-900 light:bg-white border border-gray-800 rounded-xl shadow-2xl p-6 space-y-4">
        <button type="button" onClick={onClose} className="absolute top-4 right-4 text-gray-400 hover:text-gray-200 text-xl leading-none" aria-label="close">×</button>
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-blue-400 uppercase">Evidence</div>
          <h2 className="text-base font-bold text-gray-100 font-mono mt-0.5">
            {cell.feature} · {SURFACE_LABELS[cell.surface] ?? cell.surface} · {cell.model_id}
          </h2>
          <div className="text-xs text-gray-500 mt-0.5">{cell.model_name}</div>
        </div>

        <div className="bg-gray-950/60 light:bg-gray-50 border border-gray-800 rounded-xl p-4 space-y-2">
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-bold font-mono text-gray-100">{cell.model_name}</span>
            <span className={`px-2.5 py-0.5 text-[11px] font-medium rounded-full border ${STATUS_STYLE[cell.status]}`}>
              {STATUS_LABEL[cell.status]}
            </span>
          </div>
          <div className="text-xs text-gray-500">
            latency: <span className="text-gray-300 font-semibold tabular-nums">{cell.latency_ms != null ? `${Math.round(cell.latency_ms)} ms` : "-"}</span>
          </div>
          <p className={`text-sm leading-relaxed ${isOk ? "text-gray-300" : cell.status === "broken" ? "text-rose-300" : "text-amber-300"}`}>
            {verdict}
          </p>

          {error && <div className="text-xs text-rose-400">증거 로드 실패: {error}</div>}
          {data && (
            <div className="space-y-1 pt-1">
              {errorMsg && <Section title="Error" json={errorMsg} tone="error" />}
              {request && <Section title="Request JSON" json={request} />}
              <Section title="Response JSON" json={response} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ParityPanel() {
  const { lang } = useLang();
  const [run, setRun] = useState<ParityRunInfo | null>(null);
  const [results, setResults] = useState<ParityCell[]>([]);
  const [features, setFeatures] = useState<Feature[]>([]);
  const [surfaces, setSurfaces] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [statusFilter, setStatusFilter] = useState<Status | "all">("all");
  const [selected, setSelected] = useState<ParityCell | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);
  const [changes, setChanges] = useState<ParityChange[]>([]);
  const [prevRunId, setPrevRunId] = useState<number | null>(null);
  const [providerDetail, setProviderDetail] = useState<string | null>(null);

  const load = () => {
    Promise.all([
      fetch(`${BASE}/api/parity/latest`).then((r) => r.json()),
      fetch(`${BASE}/api/parity/catalog`).then((r) => r.json()),
    ])
      .then(([latest, catalog]) => {
        setRun(latest.run);
        setResults(latest.results);
        setChanges(latest.changes ?? []);
        setPrevRunId(latest.previous_run_id ?? null);
        setFeatures(catalog.features);
        setSurfaces(catalog.surfaces);
      })
      .catch((e) => console.error("parity load failed:", e))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const handleTrigger = async () => {
    const token = getToken();
    if (!token) {
      setTriggerMsg(lang === "en" ? "Login required to trigger a run." : "런 실행에는 로그인이 필요합니다.");
      return;
    }
    const res = await fetch(`${BASE}/api/parity/trigger`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    });
    const body = await res.json().catch(() => ({}));
    setTriggerMsg(body.message ?? `HTTP ${res.status}`);
  };

  // provider별 요약 카드 (v2.12.0) — Anthropic / OpenAI / Amazon
  const providerStats = useMemo<ProviderStat[]>(() => {
    const per = new Map<string, Record<Status, number>>();
    for (const r of results) {
      const p = providerOf(r.model_id);
      const c = per.get(p) ?? { supported: 0, unsupported: 0, broken: 0, skipped: 0 };
      c[r.status] += 1;
      per.set(p, c);
    }
    const order = ["Anthropic", "OpenAI", "Amazon"];
    return Array.from(per.entries())
      .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
      .map(([provider, counts]) => ({
        provider,
        counts,
        total: counts.supported + counts.unsupported + counts.broken + counts.skipped,
        health: Math.round((100 * counts.supported) / Math.max(1, counts.supported + counts.broken)),
      }));
  }, [results]);

  // 모델 선택 드롭다운용 — 매트릭스 등장 순서의 고유 모델명
  const modelNames = useMemo(
    () => Array.from(new Set(results.map((r) => r.model_name))),
    [results],
  );
  const pickerItems = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? modelNames.filter((n) => n.toLowerCase().includes(q)) : modelNames;
  }, [modelNames, search]);

  // 피처별 그룹 구성 (v2.15.0) — 요약행(분포 카운트) + 모델 행, 접이식
  const groups = useMemo(() => {
    const byKey = new Map<string, ParityCell>();
    for (const r of results) byKey.set(`${r.feature}|${r.model_id}|${r.surface}`, r);
    const models = Array.from(new Map(results.map((r) => [r.model_id, r.model_name])).entries());
    const q = search.trim().toLowerCase();
    const out: {
      feature: string;
      label: string;
      desc: string;
      counts: Record<Status, number>;
      rows: { model_id: string; model_name: string; cells: (ParityCell | null)[] }[];
    }[] = [];
    for (const f of features) {
      const counts: Record<Status, number> = { supported: 0, unsupported: 0, broken: 0, skipped: 0 };
      for (const r of results) if (r.feature === f.id && r.status !== "skipped") counts[r.status] += 1;
      const rows: { model_id: string; model_name: string; cells: (ParityCell | null)[] }[] = [];
      for (const [model_id, model_name] of models) {
        if (q && !model_name.toLowerCase().includes(q) && !model_id.toLowerCase().includes(q)) continue;
        const cells = surfaces.map((s) => byKey.get(`${f.id}|${model_id}|${s}`) ?? null);
        if (!cells.some((c) => c && c.status !== "skipped")) continue; // 전부 미해당인 모델 행 숨김
        if (statusFilter !== "all" && !cells.some((c) => c && c.status === statusFilter)) continue;
        rows.push({ model_id, model_name, cells });
      }
      if (rows.length === 0 && (q || statusFilter !== "all")) continue; // 필터에 안 걸린 피처 숨김
      out.push({
        feature: f.id,
        label: lang === "en" ? f.id : f.label_ko,
        desc: f.desc_ko,
        counts,
        rows,
      });
    }
    return out;
  }, [results, features, surfaces, search, statusFilter, lang]);

  // 접기/펼치기 — 기본: Broken 포함 피처만 펼침. 검색/필터 중에는 전체 펼침.
  const [expandedFeatures, setExpandedFeatures] = useState<Set<string> | null>(null);
  const filterActive = search.trim() !== "" || statusFilter !== "all";
  const effectiveExpanded = useMemo(() => {
    if (filterActive) return new Set(groups.map((g) => g.feature));
    if (expandedFeatures) return expandedFeatures;
    return new Set(groups.filter((g) => g.counts.broken > 0).map((g) => g.feature));
  }, [filterActive, expandedFeatures, groups]);
  const toggleFeature = (fid: string) => {
    if (filterActive) return;
    const next = new Set(effectiveExpanded);
    if (next.has(fid)) next.delete(fid); else next.add(fid);
    setExpandedFeatures(next);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      {/* 헤더 + 요약 */}
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-100">{lang === "en" ? "Parity Run" : "패리티 런"}</h2>
          <p className="text-sm text-gray-400 mt-1 max-w-3xl leading-relaxed">
            {lang === "en"
              ? "Every cell is backed by a real API call — probes inspect response content, HTTP 200 is never enough."
              : "모든 셀은 실제 API 호출로 검증됩니다 — 프로브가 응답 내용을 검사하며, HTTP 200만으로는 판정하지 않습니다."}
          </p>
          {run && (
            <p className="text-xs text-gray-500 mt-1">
              {lang === "en" ? "Last run" : "최근 런"} #{run.id} ·{" "}
              {run.finished_at ? new Date(run.finished_at).toLocaleString() : "-"}
              {run.running && <span className="ml-2 text-blue-400">● {lang === "en" ? "run in progress…" : "런 실행 중…"}</span>}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleTrigger}
            className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
          >
            {lang === "en" ? "Run parity sweep" : "패리티 런 실행"}
          </button>
        </div>
      </div>
      {triggerMsg && (
        <div className="px-3 py-2 bg-blue-500/10 border border-blue-500/30 rounded-md text-xs text-blue-300">{triggerMsg}</div>
      )}

      {/* 이전 런 대비 변경사항 (v2.12.0) */}
      {run && changes.length > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4">
          <div className="text-sm font-semibold text-amber-300 mb-2">
            {lang === "en"
              ? `Changes since run #${prevRunId}: ${changes.length}`
              : `이전 런(#${prevRunId}) 대비 변경 ${changes.length}건`}
          </div>
          <ul className="space-y-1 text-xs text-gray-300">
            {changes.slice(0, 10).map((c) => {
              const featureLabel = features.find((f) => f.id === c.feature)?.label_ko ?? c.feature;
              return (
                <li key={`${c.model_id}|${c.surface}|${c.feature}`} className="flex items-center gap-2 flex-wrap">
                  <span className="text-gray-400">{c.model_name}</span>
                  <span className="text-gray-600">·</span>
                  <span>{lang === "en" ? c.feature : featureLabel} / {SURFACE_LABELS[c.surface] ?? c.surface}</span>
                  <span className="text-gray-600">:</span>
                  <span className={c.before ? "" : "text-gray-500"}>{c.before ?? (lang === "en" ? "new" : "신규")}</span>
                  <span className="text-gray-500">→</span>
                  <span className={c.after === "supported" ? "text-emerald-300" : c.after === "broken" ? "text-rose-300" : "text-amber-300"}>
                    {c.after}
                  </span>
                </li>
              );
            })}
            {changes.length > 10 && (
              <li className="text-gray-500">{lang === "en" ? `+${changes.length - 10} more` : `외 ${changes.length - 10}건`}</li>
            )}
          </ul>
        </div>
      )}
      {run && prevRunId != null && changes.length === 0 && (
        <div className="px-3 py-2 bg-gray-900/50 border border-gray-800 rounded-xl text-xs text-gray-500">
          {lang === "en"
            ? `No changes since run #${prevRunId}.`
            : `이전 런(#${prevRunId}) 대비 변경 없음.`}
        </div>
      )}

      {/* provider별 요약 카드 (v2.12.0) — 클릭 시 우측 상세 요약 바 */}
      {run && providerStats.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-4">
          {providerStats.map((p) => (
            <button
              key={p.provider}
              type="button"
              onClick={() => setProviderDetail(p.provider)}
              className="text-left bg-gray-900/50 border border-gray-800 hover:border-blue-500/60 rounded-xl p-4 flex items-center gap-4 transition-colors"
            >
              <Donut counts={p.counts} health={p.health} />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-base font-bold text-gray-100">{p.provider}</span>
                  <span className="px-1.5 py-0.5 text-[10px] rounded bg-gray-800 text-gray-400">{p.total} {lang === "en" ? "checks" : "검사"}</span>
                </div>
                <div className="text-[11px] text-gray-500 mt-0.5">
                  {lang === "en" ? `${p.health}% of features that should work do` : `동작해야 하는 기능 중 ${p.health}% 동작`}
                </div>
                <div className="flex items-center gap-x-3 gap-y-1 flex-wrap mt-2 text-[11px] tabular-nums">
                  <span className="text-emerald-300">● {p.counts.supported} supported</span>
                  <span className="text-amber-300">● {p.counts.unsupported} unsupported</span>
                  <span className="text-rose-300">● {p.counts.broken} broken</span>
                  <span className="text-gray-500">● {p.counts.skipped} skipped</span>
                </div>
                <div className="text-[11px] text-blue-400 mt-1.5">{lang === "en" ? "Insights →" : "상세 요약 →"}</div>
              </div>
            </button>
          ))}
        </div>
      )}

      {!run && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-8 text-center text-sm text-gray-400">
          {lang === "en"
            ? "No parity run yet — click \"Run parity sweep\" (login required) or wait for the 12-hour schedule."
            : "아직 실행된 패리티 런이 없습니다 — \"패리티 런 실행\"(로그인 필요)을 누르거나 12시간 주기 스케줄을 기다려 주세요."}
        </div>
      )}

      {/* 필터 */}
      {run && (
        <div className="flex items-center gap-3 flex-wrap">
          <div className="relative">
            <input
              type="text"
              value={search}
              onChange={(e) => { setSearch(e.target.value); setPickerOpen(true); }}
              onFocus={() => setPickerOpen(true)}
              onBlur={() => setTimeout(() => setPickerOpen(false), 150)}
              placeholder={lang === "en" ? "Select or search models..." : "모델 선택/검색..."}
              className="px-3 py-1.5 pr-8 text-sm rounded-lg bg-gray-900 light:bg-white border border-gray-800 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 w-64"
            />
            {search && (
              <button
                type="button"
                onClick={() => { setSearch(""); setPickerOpen(false); }}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-sm"
                aria-label={lang === "en" ? "clear model filter" : "모델 필터 지우기"}
              >
                ×
              </button>
            )}
            {pickerOpen && pickerItems.length > 0 && (
              <ul className="absolute z-20 mt-1 w-full max-h-72 overflow-y-auto bg-gray-900 light:bg-white border border-gray-700 rounded-lg shadow-xl py-1">
                {pickerItems.map((name) => (
                  <li key={name}>
                    <button
                      type="button"
                      onMouseDown={() => { setSearch(name); setPickerOpen(false); }}
                      className={`w-full text-left px-3 py-1.5 text-xs transition-colors hover:bg-blue-600/20 ${
                        search === name ? "text-blue-300 font-medium" : "text-gray-300"
                      }`}
                    >
                      {name}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div className="flex gap-1">
            {(["all", "supported", "unsupported", "broken"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
                  statusFilter === s ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
                }`}
              >
                {s === "all" ? (lang === "en" ? "All" : "전체") : STATUS_LABEL[s as Status]}
              </button>
            ))}
          </div>
          <span className="text-xs text-gray-500">
            {groups.length} {lang === "en" ? "features" : "피처"}
          </span>
          {!filterActive && (
            <div className="flex gap-1">
              <button
                onClick={() => setExpandedFeatures(new Set(groups.map((g) => g.feature)))}
                className="px-2 py-1 text-[11px] rounded-md bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
              >
                {lang === "en" ? "Expand all" : "모두 펼치기"}
              </button>
              <button
                onClick={() => setExpandedFeatures(new Set())}
                className="px-2 py-1 text-[11px] rounded-md bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"
              >
                {lang === "en" ? "Collapse all" : "모두 접기"}
              </button>
            </div>
          )}
        </div>
      )}

      {/* 매트릭스 */}
      {run && (
        <div className="overflow-x-auto bg-gray-900/50 border border-gray-800 rounded-xl">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left px-3 py-2 text-gray-400 font-medium sticky left-0 bg-gray-900 light:bg-white">
                  {lang === "en" ? "Feature · Model" : "기능 · 모델"}
                </th>
                {surfaces.map((s) => (
                  <th key={s} className="text-left px-3 py-2 text-gray-400 font-medium whitespace-nowrap">
                    {SURFACE_LABELS[s] ?? s}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const open = effectiveExpanded.has(g.feature);
                const probed = g.counts.supported + g.counts.unsupported + g.counts.broken;
                return (
                  <Fragment key={g.feature}>
                    {/* 피처 요약행 — 클릭으로 접기/펼치기, 상태 분포 바 표시 */}
                    <tr
                      onClick={() => toggleFeature(g.feature)}
                      className={`border-t-2 border-t-gray-700 border-b border-gray-800/60 bg-gray-900/80 light:bg-gray-50 ${filterActive ? "" : "cursor-pointer hover:bg-gray-800/60"}`}
                      title={g.desc}
                    >
                      <td className="px-3 py-2 sticky left-0 bg-gray-900 light:bg-white">
                        <div className="flex items-center gap-2">
                          {!filterActive && (
                            <span className={`text-[10px] text-gray-500 transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
                          )}
                          <span className="font-bold text-gray-100 text-sm">{g.label}</span>
                        </div>
                      </td>
                      <td className="px-3 py-2" colSpan={surfaces.length}>
                        <div className="flex items-center gap-3">
                          <div className="flex h-1.5 w-40 rounded-full overflow-hidden bg-gray-800 shrink-0">
                            {(["supported", "unsupported", "broken"] as Status[]).map((s) =>
                              g.counts[s] > 0 ? (
                                <div
                                  key={s}
                                  className={s === "supported" ? "bg-emerald-400" : s === "unsupported" ? "bg-amber-400" : "bg-rose-400"}
                                  style={{ width: `${(100 * g.counts[s]) / Math.max(1, probed)}%` }}
                                />
                              ) : null,
                            )}
                          </div>
                          <span className="text-[11px] text-gray-500 tabular-nums whitespace-nowrap">
                            <span className="text-emerald-300">{g.counts.supported}</span>
                            {" · "}
                            <span className="text-amber-300">{g.counts.unsupported}</span>
                            {" · "}
                            <span className={g.counts.broken > 0 ? "text-rose-300 font-semibold" : "text-gray-500"}>{g.counts.broken}</span>
                            <span className="text-gray-600"> / {probed}</span>
                          </span>
                        </div>
                      </td>
                    </tr>
                    {open &&
                      g.rows.map((row) => (
                        <tr key={`${g.feature}|${row.model_id}`} className="border-b border-gray-800/60">
                          <td className="px-3 py-1.5 pl-8 sticky left-0 bg-gray-900 light:bg-white">
                            <div className="text-gray-300 text-[11px]">{row.model_name}</div>
                            <div className="text-gray-500 font-mono text-[10px]">{row.model_id}</div>
                          </td>
                          {row.cells.map((cell, j) => (
                            <td key={j} className="px-3 py-1.5">
                              {cell && cell.status !== "skipped" ? (
                                <button
                                  onClick={() => setSelected(cell)}
                                  className={`px-2 py-0.5 text-[10px] font-medium rounded-full border transition-transform hover:scale-105 ${STATUS_STYLE[cell.status]}`}
                                  title={`${Math.round(cell.latency_ms ?? 0)} ms — 클릭해서 증거 보기`}
                                >
                                  {STATUS_LABEL[cell.status]}
                                </button>
                              ) : (
                                <span className="text-gray-600">—</span>
                              )}
                            </td>
                          ))}
                        </tr>
                      ))}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 동작 방식 요약 */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 text-xs text-gray-400 leading-relaxed space-y-1.5">
        <div className="text-sm font-semibold text-gray-200 mb-1">{lang === "en" ? "How it works" : "동작 방식"}</div>
        <p>1 · {lang === "en" ? "An EventBridge schedule starts a Fargate sweep every 12 hours (manual trigger runs inside the backend service)." : "EventBridge 스케줄이 12시간마다 Fargate 스윕을 시작합니다 (수동 트리거는 backend 서비스 내에서 실행)."}</p>
        <p>2 · {lang === "en" ? "The monitored model catalog is the source — new models are picked up automatically." : "모니터링 모델 카탈로그가 소스입니다 — 신규 모델은 자동으로 반영됩니다."}</p>
        <p>3 · {lang === "en" ? "Fan-out across model × API surface (Converse / InvokeModel / Messages / ChatCompletions / Responses) × 19 features." : "모델 × API surface(Converse/InvokeModel/Messages/ChatCompletions/Responses) × 19개 피처로 팬아웃합니다."}</p>
        <p>4 · {lang === "en" ? "Execution-evidence probes: tool canary round-trip, system-instruction canary, JSON validity, cached_tokens on repeat, ≥2 stream deltas — HTTP 200 is never enough." : "실행-증거 프로브: 도구 카나리 왕복, 시스템 지시 카나리, JSON 유효성, 반복 요청의 cached tokens, 스트림 델타 2개 이상 — HTTP 200만으로는 판정하지 않습니다."}</p>
        <p>5 · {lang === "en" ? "Execution evidence (response snippet, tool call, usage, latency, error) is stored in RDS; click any cell to see it. Changes vs the previous run are shown at the top." : "실행 증거(응답 스니펫·도구 호출·usage·지연·오류)는 RDS에 저장됩니다. 셀을 클릭하면 확인할 수 있고, 이전 런 대비 변경사항은 상단에 표시됩니다."}</p>
      </div>

      {selected && run && <EvidenceModal runId={run.id} cell={selected} onClose={() => setSelected(null)} />}
      {providerDetail && (
        <ProviderDrawer
          provider={providerDetail}
          cells={results.filter((r) => providerOf(r.model_id) === providerDetail)}
          features={features}
          lang={lang}
          onClose={() => setProviderDetail(null)}
        />
      )}
    </div>
  );
}
