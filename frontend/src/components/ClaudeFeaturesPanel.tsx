"use client";

// Claude API Features (v2.23.0) — platform.claude.com "Build with Claude" 33피처(+코어 4, Models API)를
// Claude Platform on AWS / Bedrock Mantle / Bedrock runtime(Messages API · InvokeModel · Converse) 5열에서 실행-증거로 검증.
// 표 하단 "참조" 블록: Mantle에서 측정 불가한 모델(Fable 5.1 = US GovCloud 전용)을 카탈로그 mantle_reason으로 표기 (v2.23.1).
// 셀 = 피처 × 엔드포인트(대표 모델 4종 집계) — 클릭 시 모델별 상세, 문서 기대치 vs 실측 드리프트 배너.

import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { useLang } from "@/lib/i18n-context";
import {
  fetchFeaturesCatalog, fetchFeaturesEvidence, fetchFeaturesLatest, getToken, triggerFeaturesRun,
  type FeaturesCatalog, type FeaturesEvidence, type FeaturesLatest,
} from "@/lib/api";
import {
  aggregateCell, buildGroups, cellBadge, cellLatencyLines, featureLabelOf, findCell, formatDuration, formatMs, isGroupOpen, isProbed, labelMaps,
  pickModel, runSummary, summarizeChanges, surfaceFindings, surfaceShortOf, surfaceSummary, visibleSegments,
  CHANGE_KIND_LABEL, DOC_LABEL, SEGMENT_BAR_COLOR, SEGMENT_LABEL, SEGMENT_ORDER, SEGMENT_TEXT, STATUS_LABEL, STATUS_STYLE, STATUS_TEXT, VERDICT_STYLE,
  type CellAggregate, type CellStatus, type FeatureCell, type FindingChip, type FindingFeatureGroup, type LabelMaps, type RowView,
  type SurfaceDef, type SurfaceFindings, type SurfaceSummary,
} from "@/lib/claudeFeatures";

const SURFACE_GROUP_LABEL: Record<string, { en: string; ko: string }> = {
  cp: { en: "Claude Platform on AWS", ko: "Claude Platform on AWS" },
  mantle: { en: "Bedrock Mantle", ko: "Bedrock Mantle" },
  bedrock: { en: "Bedrock runtime", ko: "Bedrock runtime" },
};

function EvidenceModal({ runId, cell, labels, onClose }: { runId: number; cell: FeatureCell; labels: LabelMaps; onClose: () => void }) {
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
          <h2 className="text-base font-bold text-gray-100 mt-0.5">{featureLabelOf(labels, cell.feature)} · {surfaceShortOf(labels, cell.surface)} · {cell.model_label}</h2>
          <div className="text-xs text-gray-500 mt-0.5 font-mono">{cell.feature} · {cell.surface} · {cell.model_id ?? "—"}</div>
        </div>
        <div className="bg-gray-950/60 light:bg-gray-50 border border-gray-800 rounded-xl p-4 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-2.5 py-0.5 text-[11px] font-medium rounded-full border ${STATUS_STYLE[cell.status]}`}>{STATUS_LABEL[cell.status]}</span>
            <span className="text-xs text-gray-500">{lang === "en" ? "documented" : "문서"}: <b className="text-gray-300">{DOC_LABEL[cell.documented]}</b></span>
            <span className={`text-xs ${VERDICT_STYLE[cell.verdict]}`}>{lang === "en" ? "verdict" : "판정"}: {cell.verdict}</span>
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

// Key Findings 드로어 (v2.24.0, D4) — surface 카드 클릭 → verdict 축 6섹션. 라벨은 카탈로그 LabelMaps(D2/RUL-6), 항목·칩 클릭 → 증거 모달(RUL-9).
function SurfaceDrawer({ surface, findings, labels, onPick, onClose }: {
  surface: SurfaceDef; findings: SurfaceFindings; labels: LabelMaps;
  onPick: (c: FeatureCell) => void; onClose: () => void;
}) {
  const { lang } = useLang();
  const T = (en: string, ko: string) => (lang === "en" ? en : ko);
  const label = (id: string) => featureLabelOf(labels, id);
  const none = (
    <div className="text-xs text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 rounded-lg px-3 py-2">{T("None.", "없음")}</div>
  );

  const Sec = ({ title, sub, color, empty, children }: { title: string; sub: string; color: string; empty: boolean; children: ReactNode }) => (
    <section>
      <h3 className={`text-sm font-semibold mb-1 ${color}`}>{title}</h3>
      <p className="text-[11px] text-gray-500 mb-2">{sub}</p>
      {empty ? none : children}
    </section>
  );
  const GroupCards = ({ groups, tone }: { groups: FindingFeatureGroup[]; tone: "rose" | "amber" }) => (
    <div className="space-y-2">
      {groups.map((g) => (
        <div key={g.feature} className={`rounded-lg px-3 py-2 border ${tone === "rose" ? "bg-rose-500/10 border-rose-500/20" : "bg-amber-500/10 border-amber-500/20"}`}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium text-gray-100">{label(g.feature)}</span>
            <span className={`text-xs font-semibold whitespace-nowrap ${tone === "rose" ? "text-rose-300" : "text-amber-300"}`}>{g.count}/{g.probed} {T("cells", "셀")}</span>
          </div>
          <div className="text-[11px] text-gray-500 font-mono mt-0.5">{g.feature}</div>
          <div className="flex flex-wrap gap-1 mt-1">
            {g.cells.map((c) => (
              <button key={c.model_key} type="button" onClick={() => onPick(c)} title={T("Open evidence", "증거 보기")}
                className="px-1.5 py-0.5 text-[10px] rounded border border-gray-700 text-gray-300 hover:border-blue-500/60 hover:text-blue-300">
                {c.model_label}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
  // RUL-9: 칩은 button — 첫 모델의 증거 모달을 연다. title에 모델 전체 목록.
  const Chips = ({ chips, style }: { chips: FindingChip[]; style: string }) => (
    <div className="flex flex-wrap gap-1.5">
      {chips.map((u) => (
        <button key={u.feature} type="button" onClick={() => onPick(u.cells[0])}
          title={`${u.models.join(", ")} (${T("click: evidence of the first model", "클릭: 첫 모델 증거")})`}
          className={`px-2 py-0.5 text-[11px] rounded-full border hover:border-blue-500/60 ${style}`}>
          {label(u.feature)}
        </button>
      ))}
    </div>
  );

  return (
    <div className="fixed inset-0 z-50">
      <button type="button" aria-label="overlay" onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <aside className="absolute right-0 top-0 h-full w-full max-w-md overflow-y-auto bg-gray-900 light:bg-white border-l border-gray-800 shadow-2xl p-6 space-y-6">
        <div>
          <div className="text-[11px] font-semibold tracking-wider text-blue-400 uppercase">Key Findings</div>
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-bold text-gray-100">{surface.label}</h2>
            <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-200 text-xl leading-none" aria-label="close">×</button>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            <span className="font-mono">{surface.id}</span> · <span className="font-mono">{surface.region}</span> · {T(`latest run, computed from all ${findings.total} cells of this endpoint`, `최근 런 기준, 이 엔드포인트의 전체 ${findings.total}셀에서 계산`)}
          </p>
        </div>

        <Sec color="text-rose-300" empty={findings.drift.length === 0}
          title={T(`1. Documentation drift (${findings.drift.length} features)`, `1. 문서 드리프트 (${findings.drift.length}개 피처)`)}
          sub={T("Documented GA/Beta but measured unsupported or broken. Check the request snapshot in the evidence modal for a probe defect first.",
                 "문서상 GA/Beta인데 실측이 unsupported 또는 broken인 셀입니다. 증거 모달의 요청 스냅샷으로 프로브 결함 여부를 먼저 확인합니다.")}>
          <GroupCards groups={findings.drift} tone="rose" />
        </Sec>

        <Sec color="text-rose-300" empty={findings.broken.length === 0}
          title={T(`2. Probe errors (${findings.broken.length} features)`, `2. 프로브 오류 (${findings.broken.length}개 피처)`)}
          sub={T("Cells that returned an error instead of a response. Listed by status (broken) regardless of the documented expectation.",
                 "응답 대신 오류를 받은 셀입니다. 문서 기대치와 무관하게 status가 broken이면 여기에 옵니다.")}>
          <GroupCards groups={findings.broken} tone="rose" />
        </Sec>

        <Sec color="text-amber-300" empty={findings.intendedGaps.length === 0}
          title={T(`3. Intended gaps (${findings.intendedGaps.length})`, `3. 의도된 격차 (${findings.intendedGaps.length})`)}
          sub={T("Documented as unavailable and measured unsupported (not a bug).", "문서상 미제공, 실측도 미지원 (버그 아님)")}>
          <Chips chips={findings.intendedGaps} style={STATUS_STYLE.unsupported} />
        </Sec>

        <Sec color="text-gray-300" empty={findings.undecidedGaps.length === 0}
          title={T(`4. Documentation undecided (${findings.undecidedGaps.length})`, `4. 문서 미확정 (${findings.undecidedGaps.length})`)}
          sub={T("Documented expectation is unknown and the probe measured unsupported. Once the docs settle, these move to drift or intended gaps.",
                 "문서 기대치가 unknown인데 실측 미지원인 피처입니다. 문서가 확정되면 드리프트 또는 의도된 격차로 귀속됩니다.")}>
          <Chips chips={findings.undecidedGaps} style="bg-gray-800 border-gray-700 text-gray-400" />
        </Sec>

        <Sec color="text-sky-300" empty={findings.undocumented.length === 0}
          title={T(`5. Undocumented behaviour (${findings.undocumented.length})`, `5. 문서에 없는 동작 (${findings.undocumented.length})`)}
          sub={T("Not promised by the docs, yet measured supported.", "문서가 약속하지 않았지만 실측이 supported인 피처입니다.")}>
          <Chips chips={findings.undocumented} style="bg-sky-500/10 border-sky-500/30 text-sky-300" />
        </Sec>

        <section>
          <h3 className="text-sm font-semibold text-gray-200 mb-1">{T("6. Documented health per model", "6. 모델별 문서 일치율")}</h3>
          <p className="text-[11px] text-gray-500 mb-2">
            {T("Share of documented GA/Beta cells that measured supported. Models not served here show the reason instead of a bar.",
               "문서상 GA/Beta 셀 중 supported 비율입니다. 측정 불가 모델은 막대 대신 사유를 표기합니다.")}
          </p>
          <div className="space-y-1.5">
            {findings.perModel.map((m) => (
              <div key={m.model_key} className="flex items-center gap-2 text-[11px]">
                <span className="w-24 shrink-0 truncate text-gray-300">{m.model_label.replace(/^Claude /, "")}</span>
                {m.na_reason ? (
                  <span className="flex-1 text-gray-500 leading-snug">{m.na_reason}</span>
                ) : m.docHealth == null ? (
                  <span className="flex-1 text-gray-500">{T("no documented probed cells", "문서상 프로브 셀 없음")}</span>
                ) : (
                  <>
                    <div className="flex-1 h-1.5 rounded-full bg-gray-800 overflow-hidden">
                      <div className={`h-full rounded-full ${m.docHealth < 60 ? "bg-rose-400" : "bg-emerald-400"}`} style={{ width: `${m.docHealth}%` }} />
                    </div>
                    <span className="w-28 text-right text-gray-400 tabular-nums whitespace-nowrap">
                      {m.docHealth}% ({m.supported}/{m.probed}){m.drift > 0 && <span className="text-rose-300 ml-1">▲{m.drift}</span>}
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
        </section>
      </aside>
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
  const lines = cellLatencyLines(agg.cells);
  const hint = badge.documentedOnly
    ? (lang === "en" ? "Documented as available — no verification path on this endpoint (not measured)" : "문서상 지원 — 이 엔드포인트에는 실측 경로가 없어 측정하지 않음")
    : (lang === "en" ? "Click for per-model evidence" : "클릭해서 모델별 증거 보기");
  // D6: 모델별 "라벨: N ms" 줄 + 지표 성격 한 줄 + 기존 안내. title은 \n으로 줄바꿈 렌더. L()은 메인 컴포넌트 클로저라 여기서는 삼항.
  const title = lines.length === 0 ? hint
    : [...lines.map((l) => `${l.model_label}: ${formatMs(l.ms)}`), lang === "en" ? "probe wall-clock time (multi-call probes are summed)" : "프로브 소요 시간(wall-clock, 다중 호출 프로브는 합산)", hint].join("\n");
  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => (single ? onPick(agg.cells[0]) : setOpen((o) => !o))}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        className={`px-2 py-0.5 text-[10px] font-medium rounded-full border transition-transform hover:scale-105 ${badge.style}`}
        title={title}
      >
        {badge.label}
        {!single && agg.probed > 0 && <span className="ml-1 text-gray-400">{agg.counts.supported}/{agg.probed}</span>}
        {drift > 0 && <span className="ml-1 text-rose-300">▲{drift}</span>}
      </button>
      {open && (
        <ul className="absolute z-20 mt-1 left-0 min-w-[17rem] bg-gray-900 light:bg-white border border-gray-700 rounded-lg shadow-xl py-1">
          {agg.cells.map((c) => (
            <li key={c.model_key}>
              <button type="button" onMouseDown={() => onPick(c)} className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-[11px] hover:bg-blue-600/20">
                <span className="flex flex-col items-start min-w-0">
                  <span className="text-gray-300">{c.model_label}</span>
                  <span className="font-mono text-[9px] text-gray-500 truncate max-w-[11rem]">{c.model_id ?? "—"}</span>
                </span>
                <span className="flex items-center gap-2 shrink-0">
                  <span className="tabular-nums text-gray-500">{isProbed(c.status) ? formatMs(c.latency_ms) : "-"}</span>
                  <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${cellBadge(c.status, c.documented, lang).style}`}>{cellBadge(c.status, c.documented, lang).label}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// 헬스 카드 분포 막대 — parity HealthBar(ParityPanel.tsx:93-110) 이식, features 6세그먼트 (v2.24.0, D1)
function HealthBar({ summary, lang }: { summary: SurfaceSummary; lang: "en" | "ko" }) {
  const total = Math.max(1, summary.total);
  return (
    <div className="flex h-2 w-full rounded-full overflow-hidden bg-gray-800" role="img"
         aria-label={SEGMENT_ORDER.map((seg) => `${SEGMENT_LABEL[seg][lang]} ${summary.segments[seg]}`).join(", ")}>
      {SEGMENT_ORDER.map((seg) =>
        summary.segments[seg] > 0 ? (
          <div key={seg} className={SEGMENT_BAR_COLOR[seg]} style={{ width: `${(100 * summary.segments[seg]) / total}%` }}
               title={`${SEGMENT_LABEL[seg][lang]} ${summary.segments[seg]}`} />
        ) : null,
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
  const [modelFilter, setModelFilter] = useState<string | null>(null);   // D5 모델 칩 (catalog.models[].key), null = 전체 집계
  const [selected, setSelected] = useState<FeatureCell | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [surfaceDetail, setSurfaceDetail] = useState<string | null>(null);   // Key Findings 드로어 대상 surface id (D4)
  // 필터가 켜져 있으면 접힘을 무시하고 전부 펼침 (D7). 모델 칩(D5)은 행을 숨기지 않으므로 여기에 포함하지 않는다 (RUL-8).
  const filterActive = filter !== "all";

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
  const labels = useMemo(() => labelMaps(catalog, lang), [catalog, lang]);
  const cells = latest?.results ?? [];
  // D5 모델 칩: 셀·드리프트·변경을 같은 규칙으로 좁힌다 (null = 전체 집계). 헬스 카드, 배너, 드로어, 매트릭스가 같은 수를 가리켜야 한다.
  const visibleCells = useMemo(() => pickModel(cells, modelFilter), [cells, modelFilter]);
  const drift = useMemo(() => pickModel(latest?.drift ?? [], modelFilter), [latest, modelFilter]);
  const visibleChanges = useMemo(() => pickModel(latest?.changes ?? [], modelFilter), [latest, modelFilter]);
  const changeSummary = useMemo(() => summarizeChanges(visibleChanges), [visibleChanges]);
  const groups = useMemo(
    () => (catalog ? buildGroups(catalog.features, catalog.groups, surfaces, cells, lang, filter, modelFilter) : []),
    [catalog, surfaces, cells, lang, filter, modelFilter],
  );
  const run = latest?.run ?? null;
  const runTotals = runSummary(run?.totals);
  const duration = formatDuration(run?.started_at ?? null, run?.finished_at ?? null, lang);

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
              {duration && <> · {L("took", "소요")} {duration}</>}
              {run.running && <span className="ml-2 text-blue-400">● {L("run in progress…", "런 실행 중…")}</span>}
            </p>
          )}
          {/* 런 합계 스트립 (C9, v2.24.0) — 6 status 합 = 전체 셀, 드리프트는 verdict 카운트라 별도 pill (배너·카드와 같은 수를 가리켜야 함).
              run.totals는 런 전체 값이라 모델 칩 필터(D5)에 영향받지 않는다. */}
          {run && runTotals && (
            <div className="flex items-center gap-x-3 gap-y-1 flex-wrap mt-1.5 text-[11px] tabular-nums">
              <span className="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">{runTotals.total} {L("cells", "셀")}</span>
              {runTotals.statuses.map((x) => (
                <span key={x.status} className={STATUS_TEXT[x.status]}>● {x.count} {STATUS_LABEL[x.status]}</span>
              ))}
              <span className="px-1.5 py-0.5 rounded-full border border-rose-500/30 bg-rose-500/10 text-rose-300">▲ {L("drift", "드리프트")} {runTotals.drift}</span>
            </div>
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
                <button type="button" onClick={() => setSelected(c)} className="text-rose-200 hover:underline">{featureLabelOf(labels, c.feature)}</button>
                <span className="font-mono text-[10px] text-gray-600">{c.feature}</span>
                <span className="text-gray-500">{surfaceShortOf(labels, c.surface)}, {c.model_label}</span>
                <span className="text-gray-600">{L(`documented ${DOC_LABEL[c.documented]} → observed`, `문서 ${DOC_LABEL[c.documented]} → 실측`)}</span>
                <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${STATUS_STYLE[c.status]}`}>{STATUS_LABEL[c.status]}</span>
              </li>
            ))}
            {drift.length > 10 && <li className="text-gray-500">{L(`+${drift.length - 10} more`, `외 ${drift.length - 10}건`)}</li>}
          </ul>
        </div>
      )}
      {/* 드리프트 0건도 명시한다 (RUL-1) — "변경 없음" 카드와 같은 원칙: 음성 결과를 빈 화면이 아닌 문장으로 */}
      {run && drift.length === 0 && (
        <div className="px-3 py-2 bg-gray-900/50 border border-gray-800 rounded-xl text-xs text-gray-500">
          {L("No documentation drift.", "문서 드리프트 없음.")}
        </div>
      )}

      {/* 이전 런 대비 변경 (v2.24.0, D3) — previous_run_id가 있으면 항상 렌더: 목록(10건 초과 '외 N건') 또는 '변경 없음' 카드.
          항목 클릭 → latest.results에서 셀을 찾아 증거 모달. after는 6상태 STATUS_STYLE pill (critic 4-A: N/A가 amber로 찍히던 문제).
          kind 태그(카탈로그 규칙/실측)와 요약 줄은 백엔드가 kind를 내려줄 때만 표시 (RUL-4). */}
      {run && latest && visibleChanges.length > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-xs text-gray-300">
          <div className="text-sm font-semibold text-amber-300 mb-1">{L(`Changes since run #${latest.previous_run_id}: ${visibleChanges.length}`, `이전 런(#${latest.previous_run_id}) 대비 변경 ${visibleChanges.length}건`)}</div>
          {changeSummary.catalog + changeSummary.measured > 0 && (
            <div className="text-[11px] text-gray-400 mb-2">
              {L(`Catalog rule changes ${changeSummary.catalog}, measured changes ${changeSummary.measured}`, `카탈로그 규칙 변경 ${changeSummary.catalog}건, 실측 변경 ${changeSummary.measured}건`)}
            </div>
          )}
          <ul className="space-y-1">
            {visibleChanges.slice(0, 10).map((c) => {
              const target = findCell(cells, c);
              return (
                <li key={`${c.feature}|${c.surface}|${c.model_key}`} className="flex items-center gap-2 flex-wrap">
                  {c.kind && (
                    <span className={`px-1.5 py-px text-[10px] rounded ${c.kind === "catalog" ? "bg-sky-500/10 text-sky-300" : "bg-gray-800 text-gray-400"}`}>{CHANGE_KIND_LABEL[c.kind][lang]}</span>
                  )}
                  <button type="button" disabled={!target} onClick={() => target && setSelected(target)}
                          className={target ? "text-amber-100 hover:underline" : "text-gray-400 cursor-default"}>
                    {featureLabelOf(labels, c.feature)}
                  </button>
                  <span className="font-mono text-[10px] text-gray-600">{c.feature}</span>
                  <span className="text-gray-500">{surfaceShortOf(labels, c.surface)}, {c.model_label}:</span>
                  <span className={c.before ? "text-gray-300" : "text-gray-500"}>{c.before ? STATUS_LABEL[c.before] : L("new", "신규")}</span>
                  <span className="text-gray-500">→</span>
                  <span className={`px-1.5 py-0.5 rounded-full border text-[10px] ${STATUS_STYLE[c.after]}`}>{STATUS_LABEL[c.after]}</span>
                </li>
              );
            })}
            {visibleChanges.length > 10 && <li className="text-gray-500">{L(`+${visibleChanges.length - 10} more`, `외 ${visibleChanges.length - 10}건`)}</li>}
          </ul>
        </div>
      )}
      {run && latest && latest.previous_run_id != null && visibleChanges.length === 0 && (
        <div className="px-3 py-2 bg-gray-900/50 border border-gray-800 rounded-xl text-xs text-gray-500">
          {L(`No changes since run #${latest.previous_run_id}.`, `이전 런(#${latest.previous_run_id}) 대비 변경 없음.`)}
        </div>
      )}

      {/* 엔드포인트 헬스 카드 (v2.24.0, D1) — 헤드라인 = 문서 기준 헬스(docHealth: 문서상 GA/Beta ∧ 실측된 셀 중 supported 비율),
          6세그먼트 분포 막대(전체 셀), "{total} 셀" 칩(N/A 포함), 드리프트 pill(>0). docProbed=0이면 "-" (critic 4-C).
          카운트 줄은 visibleSegments (RUL-5: supported/unsupported/broken 항상, 나머지는 >0일 때만).
          카드 전체가 <button> — 클릭 시 해당 surface의 SurfaceDrawer(D4). 내부 마크업은 카드 그대로. */}
      {run && catalog && (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
          {catalog.surfaces.map((s) => {
            const sm = surfaceSummary(visibleCells, s.id);
            return (
              <button key={s.id} type="button" onClick={() => setSurfaceDetail(s.id)}
                      className="text-left w-full bg-gray-900/50 light:bg-white border border-gray-800 hover:border-blue-500/60 rounded-xl p-4 transition-colors">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-bold text-gray-100">{s.label}</span>
                  <span className="px-1.5 py-0.5 text-[10px] rounded bg-gray-800 text-gray-400 tabular-nums">{sm.total} {L("cells", "셀")}</span>
                  {sm.drift > 0 && (
                    <span className="px-1.5 py-0.5 text-[10px] rounded-full border border-rose-500/30 bg-rose-500/10 text-rose-300 tabular-nums">▲ {L("drift", "드리프트")} {sm.drift}</span>
                  )}
                </div>
                <div className="text-[11px] text-gray-500 font-mono">{s.region}</div>
                <div className="mt-2 flex items-end gap-2">
                  <span className="text-2xl font-bold text-gray-100 tabular-nums leading-none">{sm.docHealth == null ? "-" : `${sm.docHealth}%`}</span>
                  <span className="text-[11px] text-gray-500">
                    {sm.docHealth == null
                      ? L("no documented feature measured on this endpoint", "문서상 제공 기능 중 실측된 셀 없음")
                      : L("of documented (GA/Beta) features work as measured", "문서상 제공(GA/Beta) 기능 중 실측 동작")}
                  </span>
                </div>
                <div className="mt-2"><HealthBar summary={sm} lang={lang} /></div>
                <div className="flex items-center gap-x-3 gap-y-1 flex-wrap mt-2 text-[11px] tabular-nums">
                  {visibleSegments(sm).map((seg) => (
                    <span key={seg} className={SEGMENT_TEXT[seg]}>● {sm.segments[seg]} {SEGMENT_LABEL[seg][lang]}</span>
                  ))}
                </div>
                <div className="text-[11px] text-blue-400 mt-1.5">{L("Key findings →", "상세 요약 →")}</div>
              </button>
            );
          })}
        </div>
      )}

      {!run && (
        <div className="bg-gray-900/50 border border-gray-800 rounded-xl p-8 text-center text-sm text-gray-400">
          {L("No verification run yet — click \"Run verification\" (login required) or wait for the daily schedule.", "아직 실행된 검증 런이 없습니다 — \"검증 런 실행\"(로그인 필요)을 누르거나 일일 스케줄을 기다려 주세요.")}
        </div>
      )}

      {/* 모델 칩 (v2.24.0, D5) — 전체 집계 또는 모델 하나의 열만. 행을 숨기지 않으므로 filterActive에는 포함하지 않는다 (RUL-8). */}
      {run && catalog && (
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-gray-500 mr-1">{L("Model", "모델")}</span>
          {[{ key: null as string | null, label: L("All (aggregate)", "전체") },
            ...catalog.models.map((m) => ({ key: m.key as string | null, label: m.label.replace(/^Claude /, "") }))].map((m) => (
            <button key={m.key ?? "all"} type="button" onClick={() => setModelFilter(m.key)}
              className={`px-2.5 py-1 text-xs rounded-md transition-colors ${modelFilter === m.key ? "bg-blue-600 text-white" : "bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300"}`}>
              {m.label}
            </button>
          ))}
          {modelFilter && (
            <span className="text-[11px] text-gray-500 ml-1">
              {L("Cells, health cards and banners show this model only.", "셀, 헬스 카드, 배너가 이 모델의 결과만 표시합니다.")}
            </span>
          )}
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
          {!filterActive && (
            <div className="flex gap-1 ml-auto">
              <button type="button" onClick={() => setCollapsed(new Set())}
                      className="px-2 py-1 text-[11px] rounded-md bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300">
                {L("Expand all", "모두 펼치기")}
              </button>
              <button type="button" onClick={() => setCollapsed(new Set(groups.map((g) => g.id)))}
                      className="px-2 py-1 text-[11px] rounded-md bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-300">
                {L("Collapse all", "모두 접기")}
              </button>
            </div>
          )}
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
                const open = isGroupOpen(filterActive, collapsed, g.id);
                return (
                  <Fragment key={g.id}>
                    <tr onClick={() => { if (filterActive) return; setCollapsed((c) => { const n = new Set(c); if (n.has(g.id)) n.delete(g.id); else n.add(g.id); return n; }); }}
                        className={`border-t-2 border-t-gray-700 bg-gray-900/80 light:bg-gray-50 ${filterActive ? "" : "cursor-pointer hover:bg-gray-800/60"}`}>
                      <td className="px-3 py-2 sticky left-0 bg-gray-900 light:bg-white" colSpan={1}>
                        {!filterActive && <span className={`text-[10px] text-gray-500 inline-block mr-2 transition-transform ${open ? "rotate-90" : ""}`}>▶</span>}
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

      {surfaceDetail && run && catalog && (() => {
        const sdef = catalog.surfaces.find((s) => s.id === surfaceDetail);
        if (!sdef) return null;
        return (
          <SurfaceDrawer surface={sdef} findings={surfaceFindings(visibleCells, sdef.id, catalog.models, lang)} labels={labels}
            onPick={setSelected} onClose={() => setSurfaceDetail(null)} />
        );
      })()}
      {selected && run && <EvidenceModal runId={run.id} cell={selected} labels={labels} onClose={() => setSelected(null)} />}
    </div>
  );
}
