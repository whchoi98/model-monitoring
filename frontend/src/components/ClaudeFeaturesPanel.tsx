"use client";

// Claude API Features (v2.23.0) — platform.claude.com "Build with Claude" 33피처(+코어 4, Models API)를
// Claude Platform on AWS / Bedrock Mantle / Bedrock runtime(Messages API · InvokeModel · Converse) 5열에서 실행-증거로 검증.
// 표 하단 "참조" 블록: Mantle에서 측정 불가한 모델(Fable 5.1 = US GovCloud 전용)을 카탈로그 mantle_reason으로 표기 (v2.23.1).
// 셀 = 피처 × 엔드포인트(대표 모델 4종 집계) — 클릭 시 모델별 상세, 문서 기대치 vs 실측 드리프트 배너.

import { Fragment, useEffect, useMemo, useState } from "react";
import { useLang } from "@/lib/i18n-context";
import {
  fetchFeaturesCatalog, fetchFeaturesEvidence, fetchFeaturesLatest, getToken, triggerFeaturesRun,
  type FeaturesCatalog, type FeaturesEvidence, type FeaturesLatest,
} from "@/lib/api";
import {
  aggregateCell, buildGroups, cellBadge, surfaceHealth, DOC_LABEL, STATUS_LABEL, STATUS_STYLE, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type RowView,
} from "@/lib/claudeFeatures";

const SURFACE_GROUP_LABEL: Record<string, { en: string; ko: string }> = {
  cp: { en: "Claude Platform on AWS", ko: "Claude Platform on AWS" },
  mantle: { en: "Bedrock Mantle", ko: "Bedrock Mantle" },
  bedrock: { en: "Bedrock runtime", ko: "Bedrock runtime" },
};

function EvidenceModal({ runId, cell, onClose }: { runId: number; cell: FeatureCell; onClose: () => void }) {
  const { lang } = useLang();
  const [data, setData] = useState<FeaturesEvidence | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchFeaturesEvidence({ run_id: runId, feature: cell.feature, surface: cell.surface, model_key: cell.model_key })
      .then(setData).catch((e) => setError(String(e)));
  }, [runId, cell]);

  const evidence = (data?.evidence ?? {}) as Record<string, unknown>;
  const request = evidence.request as Record<string, unknown> | undefined;
  const response: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(evidence)) if (k !== "request") response[k] = v;
  const errorMsg = data?.error_message ?? null;
  const isOk = cell.status === "supported";

  const verdictText: Record<string, string> = lang === "en"
    ? { supported: "Probe succeeded — the documented evidence signal was present in the response.",
        unsupported: "The endpoint explicitly rejected this capability (clean unsupported response).",
        broken: errorMsg ? `Expected to work but the probe failed: ${errorMsg.slice(0, 220)}` : "Evidence check failed — response received but the documented signal was missing.",
        inconclusive: "Definition accepted, but the model did not exercise the feature (e.g. tool not invoked) — not proof of absence.",
        skipped: "Documented as available, but this endpoint has no verification path (no capability endpoint) — shown as 'Documented', not measured.",
        not_applicable: `Not applicable by design: ${String(evidence.reason ?? "")}` }
    : { supported: "프로브 성공 — 문서가 정한 증거 신호가 응답에 존재합니다.",
        unsupported: "엔드포인트가 이 기능을 명시적으로 거부했습니다 (확실한 미지원 응답).",
        broken: errorMsg ? `동작해야 하는 기능인데 프로브 실패: ${errorMsg.slice(0, 220)}` : "증거 검사 실패 — 응답은 받았지만 문서상 신호가 없습니다.",
        inconclusive: "정의는 수락됐지만 모델이 기능을 사용하지 않았습니다(도구 미호출 등) — 부재의 증거는 아님.",
        skipped: "문서상 지원(GA/Beta)이지만 이 엔드포인트에는 실측 경로가 없습니다(capability 엔드포인트 부재) — '문서상 지원'으로 표기, 측정값 아님.",
        not_applicable: `설계상 부적용: ${String(evidence.reason ?? "")}` };

  const Section = ({ title, json, tone }: { title: string; json: unknown; tone?: "error" }) => (
    <details open={!isOk} className="group">
      <summary className="cursor-pointer select-none text-sm text-gray-400 hover:text-gray-200 py-1">
        <span className="inline-block w-3 text-[10px] transition-transform group-open:rotate-90">▶</span> {title}
      </summary>
      <pre className={`mt-1 rounded-lg p-3 overflow-x-auto text-xs leading-relaxed border ${
        tone === "error" ? "bg-gray-950 border-rose-500/30 text-rose-300 whitespace-pre-wrap break-all" : "bg-gray-950 border-gray-800 text-gray-200"}`}>
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
          <h2 className="text-base font-bold text-gray-100 font-mono mt-0.5">{cell.feature} · {cell.surface} · {cell.model_label}</h2>
          <div className="text-xs text-gray-500 mt-0.5 font-mono">{cell.model_id ?? "—"}</div>
        </div>
        <div className="bg-gray-950/60 light:bg-gray-50 border border-gray-800 rounded-xl p-4 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-2.5 py-0.5 text-[11px] font-medium rounded-full border ${STATUS_STYLE[cell.status]}`}>{STATUS_LABEL[cell.status]}</span>
            <span className="text-xs text-gray-500">{lang === "en" ? "documented" : "문서"}: <b className="text-gray-300">{DOC_LABEL[cell.documented]}</b></span>
            <span className={`text-xs ${VERDICT_STYLE[cell.verdict]}`}>verdict: {cell.verdict}</span>
            {data?.verification && <span className="px-1.5 py-0.5 text-[10px] rounded bg-gray-800 text-gray-400">{data.verification}</span>}
            <span className="text-xs text-gray-500 ml-auto tabular-nums">{cell.latency_ms != null ? `${Math.round(cell.latency_ms)} ms` : "-"}</span>
          </div>
          <p className={`text-sm leading-relaxed ${isOk ? "text-gray-300" : cell.status === "broken" ? "text-rose-300" : "text-amber-300"}`}>{verdictText[cell.status]}</p>
          {data?.notes && <p className="text-[11px] text-gray-500">{data.notes}</p>}
          {data?.doc_url && (
            <a href={data.doc_url} target="_blank" rel="noreferrer" className="text-[11px] text-blue-400 hover:underline">
              {lang === "en" ? "Open documentation →" : "공식 문서 열기 →"}
            </a>
          )}
          {error && <div className="text-xs text-rose-400">{lang === "en" ? "Failed to load evidence" : "증거 로드 실패"}: {error}</div>}
          {data && (
            <div className="space-y-1 pt-1">
              {errorMsg && <Section title="Error" json={errorMsg} tone="error" />}
              {request && <Section title="Request JSON" json={request} />}
              <Section title="Response / evidence" json={response} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function CellBadge({ agg, documented, onPick }: { agg: CellAggregate; documented?: string; onPick: (c: FeatureCell) => void }) {
  const { lang } = useLang();
  const [open, setOpen] = useState(false);
  if (agg.status === "empty") return <span className="text-gray-600">—</span>;
  const single = agg.cells.length === 1;
  const drift = agg.cells.filter((c) => c.verdict === "drift").length;
  const badge = cellBadge(agg.status, documented, lang);
  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => (single ? onPick(agg.cells[0]) : setOpen((o) => !o))}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className={`px-2 py-0.5 text-[10px] font-medium rounded-full border transition-transform hover:scale-105 ${badge.style}`}
        title={badge.documentedOnly
          ? (lang === "en" ? "Documented as available — no verification path on this endpoint (not measured)" : "문서상 지원 — 이 엔드포인트에는 실측 경로가 없어 측정하지 않음")
          : (lang === "en" ? "Click for per-model evidence" : "클릭해서 모델별 증거 보기")}
      >
        {badge.label}
        {!single && agg.probed > 0 && <span className="ml-1 text-gray-400">{agg.counts.supported}/{agg.probed}</span>}
        {drift > 0 && <span className="ml-1 text-rose-300">▲{drift}</span>}
      </button>
      {open && (
        <ul className="absolute z-20 mt-1 left-0 min-w-[14rem] bg-gray-900 light:bg-white border border-gray-700 rounded-lg shadow-xl py-1">
          {agg.cells.map((c) => (
            <li key={c.model_key}>
              <button type="button" onMouseDown={() => onPick(c)} className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-[11px] hover:bg-blue-600/20">
                <span className="text-gray-300">{c.model_label}</span>
                <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${cellBadge(c.status, c.documented, lang).style}`}>{cellBadge(c.status, c.documented, lang).label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ClaudeFeaturesPanel() {
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const [catalog, setCatalog] = useState<FeaturesCatalog | null>(null);
  const [latest, setLatest] = useState<FeaturesLatest | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<CellStatus | "all" | "drift">("all");
  const [selected, setSelected] = useState<FeatureCell | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const load = () => {
    Promise.all([fetchFeaturesLatest(), fetchFeaturesCatalog()])
      .then(([l, c]) => { setLatest(l); setCatalog(c); })
      .catch((e) => console.error("features load failed:", e))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const handleTrigger = async () => {
    if (!getToken()) { setTriggerMsg(L("Login required to trigger a run.", "런 실행에는 로그인이 필요합니다.")); return; }
    const r = await triggerFeaturesRun();
    setTriggerMsg(r.message);
  };

  const surfaces = useMemo(() => catalog?.surfaces.map((s) => s.id) ?? [], [catalog]);
  const cells = latest?.results ?? [];
  const groups = useMemo(
    () => (catalog ? buildGroups(catalog.features, catalog.groups, surfaces, cells, lang, filter) : []),
    [catalog, surfaces, cells, lang, filter],
  );
  const run = latest?.run ?? null;
  const drift = latest?.drift ?? [];

  if (loading) {
    return <div className="flex items-center justify-center py-24"><div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" /></div>;
  }

  // 헤더 열 그룹: cp / mantle / bedrock(Messages API·InvokeModel·Converse 3열)
  const colGroups = catalog ? catalog.surfaces.reduce<{ group: string; ids: string[] }[]>((acc, s) => {
    const last = acc[acc.length - 1];
    if (last && last.group === s.group) last.ids.push(s.id); else acc.push({ group: s.group, ids: [s.id] });
    return acc;
  }, []) : [];

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-4">
        <div>
          <h2 className="text-xl font-bold text-gray-100">{L("Claude API Features", "Claude API 기능 검증")}</h2>
          <p className="text-sm text-gray-400 mt-1 max-w-3xl leading-relaxed">
            {L("Every documented \"Build with Claude\" feature, executed for real on Claude Platform on AWS, Bedrock Mantle and Bedrock runtime (Messages API · InvokeModel · Converse) with Fable 5.1 · Fable 5 · Opus 5 · Sonnet 5. Cells compare what the docs promise with what actually happened.",
               "공식 \"Build with Claude\" 문서의 모든 피처를 Claude Platform on AWS, Bedrock Mantle, Bedrock runtime(Messages API, InvokeModel, Converse)에서 Fable 5.1, Fable 5, Opus 5, Sonnet 5로 실제 실행합니다. 셀은 문서가 약속한 것과 실측을 비교합니다.")}
          </p>
          {run && (
            <p className="text-xs text-gray-500 mt-1">
              {L("Last run", "최근 런")} #{run.id} · {run.finished_at ? new Date(run.finished_at).toLocaleString() : "-"} · catalog {run.catalog_version}
              {run.running && <span className="ml-2 text-blue-400">● {L("run in progress…", "런 실행 중…")}</span>}
            </p>
          )}
        </div>
        <button onClick={handleTrigger} className="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors">
          {L("Run verification", "검증 런 실행")}
        </button>
      </div>
      {triggerMsg && <div className="px-3 py-2 bg-blue-500/10 border border-blue-500/30 rounded-md text-xs text-blue-300">{triggerMsg}</div>}

      {/* 드리프트 배너 */}
      {run && drift.length > 0 && (
        <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-4">
          <div className="text-sm font-semibold text-rose-300 mb-2">
            {L(`Documentation drift: ${drift.length} cells documented as available but not working`, `문서 드리프트: 문서상 제공인데 동작하지 않는 셀 ${drift.length}개`)}
          </div>
          <ul className="space-y-1 text-xs text-gray-300">
            {drift.slice(0, 10).map((c) => (
              <li key={`${c.feature}|${c.surface}|${c.model_key}`} className="flex items-center gap-2 flex-wrap">
                <button type="button" onClick={() => setSelected(c)} className="font-mono text-rose-200 hover:underline">{c.feature}</button>
                <span className="text-gray-500">{c.surface} · {c.model_label}</span>
                <span className="text-gray-600">documented {DOC_LABEL[c.documented]} → observed</span>
                <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${STATUS_STYLE[c.status]}`}>{STATUS_LABEL[c.status]}</span>
              </li>
            ))}
            {drift.length > 10 && <li className="text-gray-500">{L(`+${drift.length - 10} more`, `외 ${drift.length - 10}건`)}</li>}
          </ul>
        </div>
      )}
      {run && latest && latest.changes.length > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-xs text-gray-300">
          <div className="text-sm font-semibold text-amber-300 mb-1">{L(`Changes since run #${latest.previous_run_id}: ${latest.changes.length}`, `이전 런(#${latest.previous_run_id}) 대비 변경 ${latest.changes.length}건`)}</div>
          <ul className="space-y-0.5">
            {latest.changes.slice(0, 10).map((c) => (
              <li key={`${c.feature}|${c.surface}|${c.model_key}`}>
                <span className="font-mono">{c.feature}</span> · {c.surface} · {c.model_label}: {c.before ?? L("new", "신규")} → <span className={c.after === "supported" ? "text-emerald-300" : c.after === "broken" ? "text-rose-300" : "text-amber-300"}>{c.after}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* 엔드포인트 헬스 카드 */}
      {run && catalog && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
          {catalog.surfaces.map((s) => {
            const h = surfaceHealth(cells, s.id);
            return (
              <div key={s.id} className="bg-gray-900/50 light:bg-white border border-gray-800 rounded-xl p-4">
                <div className="text-sm font-bold text-gray-100">{s.label}</div>
                <div className="text-[11px] text-gray-500 font-mono">{s.region}</div>
                <div className="mt-2 flex items-end gap-2">
                  <span className="text-2xl font-bold text-gray-100 tabular-nums">{h.health}%</span>
                  <span className="text-[11px] text-gray-500 mb-1">{L("of should-work checks pass", "동작해야 하는 검사 통과")}</span>
                </div>
                <div className="text-[11px] mt-1"><span className="text-emerald-300">● {h.supported}</span> <span className="text-rose-300 ml-2">● {h.broken} broken</span></div>
              </div>
            );
          })}
        </div>
      )}

      {!run && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-8 text-center text-sm text-gray-400">
          {L("No verification run yet — click \"Run verification\" (login required) or wait for the daily schedule.", "아직 실행된 검증 런이 없습니다 — \"검증 런 실행\"(로그인 필요)을 누르거나 일일 스케줄을 기다려 주세요.")}
        </div>
      )}

      {run && (
        <div className="flex items-center gap-2 flex-wrap">
          {(["all", "drift", "supported", "partial", "unsupported", "broken", "inconclusive"] as const).map((s) => (
            <button key={s} onClick={() => setFilter(s)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${filter === s ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"}`}>
              {s === "all" ? L("All", "전체") : s === "drift" ? L("Drift", "드리프트") : STATUS_LABEL[s]}
            </button>
          ))}
          <span className="text-xs text-gray-500 ml-2">{groups.reduce((n, g) => n + g.rows.length, 0)} {L("features", "피처")}</span>
        </div>
      )}

      {run && catalog && (
        <div className="overflow-x-auto bg-gray-900/50 border border-gray-800 rounded-xl">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-gray-800">
                <th rowSpan={2} className="text-left px-3 py-2 text-gray-400 font-medium sticky left-0 bg-gray-900 light:bg-white align-bottom">{L("Feature", "피처")}</th>
                {colGroups.map((g) => (
                  <th key={g.group} colSpan={g.ids.length} className="text-center px-3 pt-2 text-gray-300 font-semibold whitespace-nowrap border-l border-gray-800">
                    {SURFACE_GROUP_LABEL[g.group]?.[lang === "en" ? "en" : "ko"] ?? g.group}
                  </th>
                ))}
              </tr>
              <tr className="border-b border-gray-800">
                {catalog.surfaces.map((s) => (
                  <th key={s.id} className="text-center px-3 pb-2 text-gray-500 font-medium whitespace-nowrap border-l border-gray-800">{s.short}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {groups.map((g) => {
                const open = !collapsed.has(g.id);
                return (
                  <Fragment key={g.id}>
                    <tr onClick={() => setCollapsed((c) => { const n = new Set(c); if (n.has(g.id)) n.delete(g.id); else n.add(g.id); return n; })}
                        className="border-t-2 border-t-gray-700 bg-gray-900/80 light:bg-gray-50 cursor-pointer hover:bg-gray-800/60">
                      <td className="px-3 py-2 sticky left-0 bg-gray-900 light:bg-white" colSpan={1}>
                        <span className={`text-[10px] text-gray-500 inline-block mr-2 transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
                        <span className="font-bold text-gray-100 text-sm">{g.label}</span>
                        <span className="ml-2 text-[11px] text-gray-500">{g.rows.length}</span>
                      </td>
                      <td colSpan={surfaces.length} />
                    </tr>
                    {open && g.rows.map((row: RowView) => (
                      <tr key={row.id} className="border-b border-gray-800/60" title={row.desc}>
                        <td className="px-3 py-1.5 pl-8 sticky left-0 bg-gray-900 light:bg-white">
                          <div className="flex items-center gap-2">
                            <span className="text-gray-200 text-[12px]">{row.label}</span>
                            {row.verification !== "evidence" && <span className="px-1 py-px text-[9px] rounded bg-gray-800 text-gray-500" title={L("Verification strength", "검증 강도")}>{row.verification}</span>}
                            {row.drift > 0 && <span className="text-[10px] text-rose-300">▲{row.drift}</span>}
                          </div>
                          <div className="text-gray-500 font-mono text-[10px]">{row.id}</div>
                        </td>
                        {surfaces.map((s) => (
                          <td key={s} className="px-3 py-1.5 border-l border-gray-800/60">
                            <div className="flex items-center justify-center gap-2">
                              <span className="w-7 text-[9px] text-gray-500 tabular-nums" title={L("documented", "문서")}>{DOC_LABEL[row.documented[s]] ?? "?"}</span>
                              <CellBadge agg={row.cells[s] ?? aggregateCell([])} documented={row.documented[s]} onPick={setSelected} />
                            </div>
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

      {/* 참조: Mantle에서 측정 불가한 모델(카탈로그 mantle=null → mantle_reason) + 문서상 '비적용' 피처(data_residency) — v2.23.1 */}
      {run && catalog && (() => {
        const notes = [
          ...catalog.models.filter((m) => m.mantle === null).map((m) =>
            lang === "en"
              ? `Bedrock Mantle / ${m.label}: not measurable — Mantle serves this model only in US GovCloud regions (us-gov-west-1); shown as N/A.`
              : `Bedrock Mantle의 ${m.label}: ${m.mantle_reason ?? "측정 불가"} → N/A로 표기.`),
          L("Data residency (inference_geo): on Amazon Bedrock (incl. Mantle) the inference region is set by the endpoint or inference profile, so the parameter is not applicable — shown as N/A, not Unsupported.",
            "데이터 레지던시(inference_geo): Amazon Bedrock(Mantle 포함)은 엔드포인트 리전/추론 프로파일이 추론 리전을 결정하므로 파라미터가 비적용입니다. 미지원이 아닌 N/A로 표기합니다."),
        ];
        return (
          <div className="px-1 text-[11px] text-gray-500 leading-relaxed space-y-0.5">
            {notes.map((n, i) => (
              <div key={i}><span className="font-semibold text-gray-400">{L("Note", "참조")} {i + 1}: </span>{n}</div>
            ))}
          </div>
        );
      })()}

      <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-4 text-xs text-gray-400 leading-relaxed space-y-1.5">
        <div className="text-sm font-semibold text-gray-200 mb-1">{L("How to read", "읽는 법")}</div>
        <p>1. {L("Rows are the features listed on platform.claude.com/docs/en/build-with-claude/overview (+4 core Messages checks and the Models API). The small GA/Beta/— tag in each cell is what the documentation says for that platform.", "행은 platform.claude.com/docs/en/build-with-claude/overview의 피처 목록(+코어 Messages 4종, Models API)입니다. 셀 앞의 GA/Beta/— 태그가 해당 플랫폼의 문서상 기대치입니다.")}</p>
        <p>2. {L("Each cell aggregates Fable 5.1, Fable 5, Opus 5 and Sonnet 5 (Fable 5.1 is not measurable on Bedrock Mantle — US GovCloud only; see the Note under the table). Click to open per-model evidence: request snapshot, response signal, error.", "각 셀은 Fable 5.1, Fable 5, Opus 5, Sonnet 5 결과를 집계합니다(Fable 5.1은 Bedrock Mantle에서 측정 불가 — US GovCloud 리전 전용, 표 하단 참조). 클릭하면 모델별 증거(요청 스냅샷, 응답 신호, 오류)를 볼 수 있습니다.")}</p>
        <p>3. {L("Drift = documented as available but observed unsupported/broken. Inconclusive = definition accepted but the model did not use the feature. N/A = not applicable by design (e.g. Converse has no field for it; inference_geo on Bedrock). 'Documented' (sky) = the docs say GA/Beta but the endpoint offers no verification path (e.g. 1M context on Mantle/Bedrock) — not a measurement.", "드리프트 = 문서상 제공인데 실측 미지원/오류. Inconclusive = 정의는 수락됐지만 모델이 기능을 쓰지 않음. N/A = 설계상 부적용(예: Converse에 해당 필드 없음, Bedrock의 inference_geo). '문서상 지원'(하늘색) = 문서는 GA/Beta이나 실측 경로가 없는 셀(예: Mantle/Bedrock의 1M 컨텍스트) — 측정값이 아님.")}</p>
        <p>4. {L("Runs daily via EventBridge → Fargate (manual trigger runs inside the backend). Evidence is stored in RDS; the previous run is diffed at the top.", "EventBridge → Fargate로 매일 실행(수동 트리거는 backend 내부). 증거는 RDS에 저장되고 직전 런 대비 변경이 상단에 표시됩니다.")}</p>
      </div>

      {selected && run && <EvidenceModal runId={run.id} cell={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
