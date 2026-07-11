"use client";

// 패리티 런 (v2.11.0) — 실제 API 호출 증거 기반의 기능 패리티 매트릭스.
// 모든 셀은 실행-증거 프로브의 판정 결과 (supported/unsupported/broken/skipped).
// 셀 클릭 → 해당 프로브의 요청 요약·응답 스니펫·오류 등 증거 표시.

import { useEffect, useMemo, useState } from "react";
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

const SURFACE_LABELS: Record<string, string> = {
  converse: "Converse",
  invoke_model: "InvokeModel",
  messages: "Messages",
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

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button type="button" aria-label="overlay" onClick={onClose} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto bg-gray-900 light:bg-white border border-gray-800 rounded-xl shadow-2xl p-6 space-y-4">
        <button type="button" onClick={onClose} className="absolute top-3 right-3 text-gray-400 hover:text-gray-200 text-xl leading-none" aria-label="close">×</button>
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-base font-bold text-gray-100">{cell.model_name}</h2>
            <span className={`px-2 py-0.5 text-[10px] font-medium rounded-full border ${STATUS_STYLE[cell.status]}`}>
              {STATUS_LABEL[cell.status]}
            </span>
          </div>
          <div className="text-xs text-gray-500 mt-1">
            {cell.feature} · {SURFACE_LABELS[cell.surface] ?? cell.surface}
            {cell.latency_ms != null && <> · {Math.round(cell.latency_ms)} ms</>}
          </div>
        </div>
        {error && <div className="text-xs text-rose-400">증거 로드 실패: {error}</div>}
        {data && (
          <>
            {Boolean(data.error_message) && (
              <div>
                <div className="text-xs font-semibold text-gray-300 mb-1">오류</div>
                <pre className="bg-rose-500/10 border border-rose-500/20 rounded-md p-3 text-xs text-rose-300 whitespace-pre-wrap break-all">{String(data.error_message)}</pre>
              </div>
            )}
            <div>
              <div className="text-xs font-semibold text-gray-300 mb-1">실행 증거 (evidence)</div>
              <pre className="bg-gray-950 border border-gray-800 rounded-md p-3 overflow-x-auto text-xs text-gray-200 leading-relaxed">
                {JSON.stringify(data.evidence ?? {}, null, 2)}
              </pre>
            </div>
          </>
        )}
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
  const [statusFilter, setStatusFilter] = useState<Status | "all">("all");
  const [selected, setSelected] = useState<ParityCell | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);

  const load = () => {
    Promise.all([
      fetch(`${BASE}/api/parity/latest`).then((r) => r.json()),
      fetch(`${BASE}/api/parity/catalog`).then((r) => r.json()),
    ])
      .then(([latest, catalog]) => {
        setRun(latest.run);
        setResults(latest.results);
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

  // (feature, model) 행 구성 — 각 행에 surface별 셀 매핑
  const matrix = useMemo(() => {
    const byKey = new Map<string, ParityCell>();
    for (const r of results) byKey.set(`${r.feature}|${r.model_id}|${r.surface}`, r);
    const models = Array.from(new Map(results.map((r) => [r.model_id, r.model_name])).entries());
    const q = search.trim().toLowerCase();
    const rows: { feature: string; model_id: string; model_name: string; cells: (ParityCell | null)[] }[] = [];
    for (const f of features) {
      for (const [model_id, model_name] of models) {
        if (q && !model_name.toLowerCase().includes(q) && !model_id.toLowerCase().includes(q)) continue;
        const cells = surfaces.map((s) => byKey.get(`${f.id}|${model_id}|${s}`) ?? null);
        if (statusFilter !== "all" && !cells.some((c) => c && c.status === statusFilter)) continue;
        rows.push({ feature: f.id, model_id, model_name, cells });
      }
    }
    return rows;
  }, [results, features, surfaces, search, statusFilter]);

  const totals = run?.totals ?? null;
  const health = totals
    ? Math.round((100 * (totals.supported ?? 0)) / Math.max(1, (totals.supported ?? 0) + (totals.broken ?? 0)))
    : null;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
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

      {/* 헬스 요약 */}
      {totals && (
        <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
          <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
            <div className="text-2xl font-bold text-gray-100 tabular-nums">{health}%</div>
            <div className="text-[11px] text-gray-500 mt-1">{lang === "en" ? "healthy (supported / should-work)" : "헬스 (동작해야 하는 것 중 동작)"}</div>
          </div>
          {(["supported", "unsupported", "broken", "skipped"] as Status[]).map((s) => (
            <div key={s} className="bg-gray-900/50 border border-gray-800 rounded-xl p-4">
              <div className={`text-2xl font-bold tabular-nums ${s === "supported" ? "text-emerald-400" : s === "broken" ? "text-rose-400" : s === "unsupported" ? "text-amber-400" : "text-gray-500"}`}>
                {totals[s] ?? 0}
              </div>
              <div className="text-[11px] text-gray-500 mt-1">{STATUS_LABEL[s] === "—" ? "Skipped" : STATUS_LABEL[s]}</div>
            </div>
          ))}
        </div>
      )}

      {!run && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-8 text-center text-sm text-gray-400">
          {lang === "en"
            ? "No parity run yet — click \"Run parity sweep\" (login required) or wait for the daily schedule."
            : "아직 실행된 패리티 런이 없습니다 — \"패리티 런 실행\"(로그인 필요)을 누르거나 일일 스케줄을 기다려 주세요."}
        </div>
      )}

      {/* 필터 */}
      {run && (
        <div className="flex items-center gap-3 flex-wrap">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={lang === "en" ? "Search models..." : "모델 검색..."}
            className="px-3 py-1.5 text-sm rounded-lg bg-gray-900 light:bg-white border border-gray-800 text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 w-56"
          />
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
          <span className="text-xs text-gray-500">{matrix.length} rows</span>
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
              {matrix.map((row, i) => {
                const featureLabel = features.find((f) => f.id === row.feature);
                const firstOfFeature = i === 0 || matrix[i - 1].feature !== row.feature;
                return (
                  <tr key={`${row.feature}|${row.model_id}`} className={`border-b border-gray-800/60 ${firstOfFeature ? "border-t-2 border-t-gray-700" : ""}`}>
                    <td className="px-3 py-1.5 sticky left-0 bg-gray-900 light:bg-white">
                      <div className="font-medium text-gray-200">{firstOfFeature ? featureLabel?.label_ko ?? row.feature : ""}</div>
                      <div className="text-gray-500 font-mono text-[10px]">{row.model_name}</div>
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
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* 동작 방식 요약 */}
      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 text-xs text-gray-400 leading-relaxed space-y-1.5">
        <div className="text-sm font-semibold text-gray-200 mb-1">{lang === "en" ? "How it works" : "동작 방식"}</div>
        <p>1 · {lang === "en" ? "Daily EventBridge schedule (or manual trigger) starts a Fargate sweep." : "일일 EventBridge 스케줄(또는 수동 트리거)이 Fargate 스윕을 시작합니다."}</p>
        <p>2 · {lang === "en" ? "The monitored model catalog is the source — new models are picked up automatically." : "모니터링 모델 카탈로그가 소스입니다 — 신규 모델은 자동으로 반영됩니다."}</p>
        <p>3 · {lang === "en" ? "Fan-out across model × API surface (Converse / InvokeModel / Messages / ChatCompletions / Responses) × 7 features." : "모델 × API surface(Converse/InvokeModel/Messages/ChatCompletions/Responses) × 7개 피처로 팬아웃합니다."}</p>
        <p>4 · {lang === "en" ? "Execution-evidence probes: tool canary round-trip, system-instruction canary, JSON validity, cached_tokens on repeat, ≥2 stream deltas — HTTP 200 is never enough." : "실행-증거 프로브: 도구 카나리 왕복, 시스템 지시 카나리, JSON 유효성, 반복 요청의 cached tokens, 스트림 델타 2개 이상 — HTTP 200만으로는 판정하지 않습니다."}</p>
        <p>5 · {lang === "en" ? "Raw evidence (request, response, latency, error) is stored in RDS; click any cell to see it." : "원시 증거(요청·응답·지연·오류)는 RDS에 저장됩니다. 셀을 클릭하면 확인할 수 있습니다."}</p>
      </div>

      {selected && run && <EvidenceModal runId={run.id} cell={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
