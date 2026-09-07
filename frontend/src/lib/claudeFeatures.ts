// Claude API Features 매트릭스 순수 로직 (v2.23.0) — 컴포넌트 밖으로 뺀 타입·스타일·집계 함수 (vitest 대상).

export type FeatureStatus = "supported" | "unsupported" | "broken" | "inconclusive" | "skipped" | "not_applicable";
export type CellStatus = FeatureStatus | "partial" | "empty";
export type Verdict = "match" | "drift" | "undocumented" | "none";
export type Documented = "ga" | "beta" | "no" | "unknown";

export interface FeatureCell {
  feature: string; surface: string; model_key: string; model_label: string; model_id: string | null;
  status: FeatureStatus; documented: Documented; verdict: Verdict; latency_ms: number | null;
}
export interface FeatureDef {
  id: string; group: string; label_ko: string; label_en: string; desc_ko: string; desc_en: string;
  doc_url: string; documented: Record<string, Documented | string>; verification: string; notes: string;
}
export interface FeatureGroupDef { id: string; label_ko: string; label_en: string }
export interface SurfaceDef { id: string; label: string; short: string; group: string; region: string }
export interface ModelDef { key: string; label: string; cp: string; mantle: string | null; bedrock: string; mantle_reason?: string }
export interface FeatureRunInfo {
  id: number; started_at: string | null; finished_at: string | null;
  totals: Record<string, number> | null; catalog_version: string | null; running: boolean;
}
export interface FeatureChange {
  feature: string; surface: string; model_key: string; model_label: string;
  before: FeatureStatus | null; after: FeatureStatus;
}

export const STATUS_STYLE: Record<CellStatus, string> = {
  supported: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  partial: "bg-teal-500/10 border-teal-500/30 text-teal-300",
  unsupported: "bg-amber-500/10 border-amber-500/30 text-amber-300",
  broken: "bg-rose-500/10 border-rose-500/30 text-rose-300",
  inconclusive: "bg-violet-500/10 border-violet-500/30 text-violet-300",
  skipped: "bg-gray-800 border-gray-700 text-gray-500",
  not_applicable: "bg-gray-800 border-gray-700 text-gray-500",
  empty: "bg-transparent border-transparent text-gray-600",
};
export const STATUS_LABEL: Record<CellStatus, string> = {
  supported: "Supported", partial: "Partial", unsupported: "Unsupported", broken: "Broken",
  inconclusive: "Inconclusive", skipped: "Skipped", not_applicable: "N/A", empty: "—",
};
export const VERDICT_STYLE: Record<Verdict, string> = {
  match: "text-emerald-300", drift: "text-rose-300 font-semibold", undocumented: "text-sky-300", none: "text-gray-500",
};
export const DOC_LABEL: Record<string, string> = { ga: "GA", beta: "Beta", no: "—", unknown: "?" };

// 실측 경로가 없어 skipped인 셀(예: 1M 컨텍스트 on Mantle/Bedrock)은 문서 기대치가 GA/Beta면
// "문서상 지원"으로 표기한다 — 측정값이 아님을 스타일(sky)로 구분 (v2.23.1).
export const DOCUMENTED_ONLY_STYLE = "bg-sky-500/10 border-sky-500/30 text-sky-300";

export function cellBadge(status: CellStatus, documented: string | undefined, lang: string): { label: string; style: string; documentedOnly: boolean } {
  if (status === "skipped" && (documented === "ga" || documented === "beta")) {
    return { label: lang === "en" ? "Documented" : "문서상 지원", style: DOCUMENTED_ONLY_STYLE, documentedOnly: true };
  }
  return { label: STATUS_LABEL[status], style: STATUS_STYLE[status], documentedOnly: false };
}

export interface CellAggregate { status: CellStatus; counts: Record<FeatureStatus, number>; probed: number; cells: FeatureCell[] }

export function aggregateCell(cells: FeatureCell[]): CellAggregate {
  const counts: Record<FeatureStatus, number> = { supported: 0, unsupported: 0, broken: 0, inconclusive: 0, skipped: 0, not_applicable: 0 };
  for (const c of cells) counts[c.status] += 1;
  const probed = counts.supported + counts.unsupported + counts.broken + counts.inconclusive;
  let status: CellStatus;
  if (cells.length === 0) status = "empty";
  else if (probed === 0) status = counts.not_applicable > 0 ? "not_applicable" : "skipped";
  else if (counts.broken > 0) status = "broken";
  else if (counts.supported === probed) status = "supported";
  else if (counts.unsupported === probed) status = "unsupported";
  else if (counts.inconclusive === probed) status = "inconclusive";
  else status = "partial";
  return { status, counts, probed, cells };
}

export interface RowView {
  id: string; label: string; desc: string; doc_url: string; verification: string; notes: string;
  documented: Record<string, string>; cells: Record<string, CellAggregate>; drift: number;
}
export interface GroupView { id: string; label: string; rows: RowView[] }

export function buildGroups(
  features: FeatureDef[], groups: FeatureGroupDef[], surfaces: string[], cells: FeatureCell[],
  lang: string, filter: CellStatus | "all" | "drift",
): GroupView[] {
  const byKey = new Map<string, FeatureCell[]>();
  for (const c of cells) {
    const k = `${c.feature}|${c.surface}`;
    const arr = byKey.get(k) ?? [];
    arr.push(c);
    byKey.set(k, arr);
  }
  const out: GroupView[] = [];
  for (const g of groups) {
    const rows: RowView[] = [];
    for (const f of features) {
      if (f.group !== g.id) continue;
      const agg: Record<string, CellAggregate> = {};
      let drift = 0;
      for (const s of surfaces) {
        const cs = byKey.get(`${f.id}|${s}`) ?? [];
        agg[s] = aggregateCell(cs);
        drift += cs.filter((c) => c.verdict === "drift").length;
      }
      const matches =
        filter === "all" ? true
        : filter === "drift" ? drift > 0
        : surfaces.some((s) => agg[s].status === filter || agg[s].cells.some((c) => c.status === filter));
      if (!matches) continue;
      rows.push({
        id: f.id, label: (lang === "en" ? f.label_en : f.label_ko) || f.id,
        desc: (lang === "en" ? f.desc_en : f.desc_ko) || "", doc_url: f.doc_url, verification: f.verification,
        notes: f.notes, documented: f.documented as Record<string, string>, cells: agg, drift,
      });
    }
    if (rows.length) out.push({ id: g.id, label: (lang === "en" ? g.label_en : g.label_ko) || g.id, rows });
  }
  return out;
}

export function surfaceHealth(cells: FeatureCell[], surface: string): { supported: number; broken: number; health: number } {
  let supported = 0, broken = 0;
  for (const c of cells) {
    if (c.surface !== surface) continue;
    if (c.status === "supported") supported += 1;
    else if (c.status === "broken") broken += 1;
  }
  return { supported, broken, health: Math.round((100 * supported) / Math.max(1, supported + broken)) };
}

// ── v2.24.0 UI detail parity — 공용 술어 (RUL-7: 여기 한 번만 정의, 드로어·지연시간 헬퍼가 import) ──────────
export const PROBED_STATUSES: ReadonlySet<FeatureStatus> = new Set<FeatureStatus>(["supported", "unsupported", "broken", "inconclusive"]);
export function isProbed(status: FeatureStatus): boolean { return PROBED_STATUSES.has(status); }
export function isDocumented(documented: Documented): boolean { return documented === "ga" || documented === "beta"; }

// ── v2.24.0 UI detail parity — 헬스 카드 요약 (C2/R2, D1), 런 합계 스트립 (C9) ────────────────────

/** 헬스 카드 막대 세그먼트 — 6상태를 표시 단위로 접음: skipped는 문서 GA/Beta면 '문서상 지원'(sky, cellBadge 규칙과 동일),
 *  나머지 skipped와 N/A는 other(gray). */
export type SummarySegment = "supported" | "unsupported" | "broken" | "inconclusive" | "documented_only" | "other";
export const SEGMENT_ORDER: SummarySegment[] = ["supported", "unsupported", "broken", "inconclusive", "documented_only", "other"];
// 누적 막대용 솔리드 색 — STATUS_STYLE(반투명 배지 배경)은 막대에서 보이지 않으므로 parity BAR_COLORS(ParityPanel.tsx:86-91) 패턴을 따름.
export const SEGMENT_BAR_COLOR: Record<SummarySegment, string> = {
  supported: "bg-emerald-400", unsupported: "bg-amber-400", broken: "bg-rose-400",
  inconclusive: "bg-violet-400", documented_only: "bg-sky-400", other: "bg-gray-600",
};
export const SEGMENT_TEXT: Record<SummarySegment, string> = {
  supported: "text-emerald-300", unsupported: "text-amber-300", broken: "text-rose-300",
  inconclusive: "text-violet-300", documented_only: "text-sky-300", other: "text-gray-500",
};
export const SEGMENT_LABEL: Record<SummarySegment, { en: string; ko: string }> = {
  supported: { en: "Supported", ko: "Supported" }, unsupported: { en: "Unsupported", ko: "Unsupported" },
  broken: { en: "Broken", ko: "Broken" }, inconclusive: { en: "Inconclusive", ko: "Inconclusive" },
  documented_only: { en: "Documented", ko: "문서상 지원" }, other: { en: "N/A", ko: "N/A" },
};
export const STATUS_TEXT: Record<FeatureStatus, string> = {
  supported: "text-emerald-300", unsupported: "text-amber-300", broken: "text-rose-300",
  inconclusive: "text-violet-300", skipped: "text-gray-500", not_applicable: "text-gray-500",
};

export interface SurfaceSummary {
  surface: string;
  total: number;                          // surface의 전체 셀 수 (N/A 포함) — 카드 "{total} 셀" 칩
  counts: Record<FeatureStatus, number>;  // 6상태 원시 카운트
  segments: Record<SummarySegment, number>;
  probed: number;                         // supported+unsupported+broken+inconclusive
  drift: number;                          // verdict === "drift"
  undocumented: number;                   // verdict === "undocumented"
  docSupported: number;                   // documented ∈ {ga,beta} ∧ supported
  docProbed: number;                      // documented ∈ {ga,beta} ∧ status ∈ probed 4상태 (inconclusive 포함 — RUL-2)
  docHealth: number | null;               // round(100·docSupported/docProbed); docProbed=0 → null (카드 "-")
  supported: number; broken: number; health: number; // surfaceHealth() 호환 필드
}

/** 헬스 카드 헤드라인은 "문서상 제공(GA/Beta) 기능 중 실측 동작 비율"(docHealth). 음성 일치(documented=no ∧ unsupported)는
 *  분모·분자 어디에도 들어가지 않는다 — match/(match+drift) 공식이 76%로 부풀던 문제의 교정(verify-R2). */
export function surfaceSummary(cells: FeatureCell[], surface: string): SurfaceSummary {
  const counts: Record<FeatureStatus, number> = { supported: 0, unsupported: 0, broken: 0, inconclusive: 0, skipped: 0, not_applicable: 0 };
  let total = 0, drift = 0, undocumented = 0, docSupported = 0, docProbed = 0, documentedOnly = 0;
  for (const c of cells) {
    if (c.surface !== surface) continue;
    total += 1;
    counts[c.status] += 1;
    if (c.verdict === "drift") drift += 1;
    else if (c.verdict === "undocumented") undocumented += 1;
    if (c.status === "skipped" && isDocumented(c.documented)) documentedOnly += 1;
    if (isDocumented(c.documented) && isProbed(c.status)) {
      docProbed += 1;
      if (c.status === "supported") docSupported += 1;
    }
  }
  const probed = counts.supported + counts.unsupported + counts.broken + counts.inconclusive;
  const segments: Record<SummarySegment, number> = {
    supported: counts.supported, unsupported: counts.unsupported, broken: counts.broken, inconclusive: counts.inconclusive,
    documented_only: documentedOnly, other: counts.skipped - documentedOnly + counts.not_applicable,
  };
  return {
    surface, total, counts, segments, probed, drift, undocumented, docSupported, docProbed,
    docHealth: docProbed === 0 ? null : Math.round((100 * docSupported) / docProbed),
    supported: counts.supported, broken: counts.broken,
    health: Math.round((100 * counts.supported) / Math.max(1, counts.supported + counts.broken)),
  };
}

const ALWAYS_SEGMENTS: ReadonlySet<SummarySegment> = new Set<SummarySegment>(["supported", "unsupported", "broken"]);
/** 헬스 카드 카운트 줄 (RUL-5): supported/unsupported/broken은 항상, inconclusive/문서상 지원/N/A는 0이 아닐 때만. */
export function visibleSegments(summary: SurfaceSummary): SummarySegment[] {
  return SEGMENT_ORDER.filter((seg) => ALWAYS_SEGMENTS.has(seg) || summary.segments[seg] > 0);
}

/** 런 합계 스트립 (C9): totals의 6 status 키는 합 = 전체 셀(780), drift는 verdict 카운트라 status와 겹침 → 별도 필드로 분리. */
export const RUN_STATUS_ORDER: FeatureStatus[] = ["supported", "unsupported", "broken", "inconclusive", "skipped", "not_applicable"];
export interface RunSummary { total: number; statuses: { status: FeatureStatus; count: number }[]; drift: number }

export function runSummary(totals: Record<string, number> | null | undefined): RunSummary | null {
  if (!totals) return null;
  const statuses = RUN_STATUS_ORDER.map((status) => ({ status, count: totals[status] ?? 0 }));
  return { total: statuses.reduce((n, x) => n + x.count, 0), statuses, drift: totals.drift ?? 0 };
}

/** finished_at − started_at → "6분 15초" / "6m 15s". 입력 누락, 역순, 파싱 실패는 null. */
export function formatDuration(startedAt: string | null, finishedAt: string | null, lang: string): string | null {
  if (!startedAt || !finishedAt) return null;
  const ms = new Date(finishedAt).getTime() - new Date(startedAt).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60), s = totalSec % 60;
  if (lang === "en") return m > 0 ? `${m}m ${s}s` : `${s}s`;
  return m > 0 ? `${m}분 ${s}초` : `${s}초`;
}

// ── v2.24.0 — 배너·모달·드로어 공용 라벨 맵 (D2, RUL-6): 카탈로그 label_ko/en + surface short 단일 출처, 미로드 시 id 폴백 ──
export interface LabelMaps { featureLabel: Map<string, string>; surfaceShort: Map<string, string> }

export function labelMaps(catalog: { features: FeatureDef[]; surfaces: SurfaceDef[] } | null | undefined, lang: string): LabelMaps {
  const featureLabel = new Map<string, string>();
  const surfaceShort = new Map<string, string>();
  for (const f of catalog?.features ?? []) featureLabel.set(f.id, (lang === "en" ? f.label_en : f.label_ko) || f.id);
  for (const s of catalog?.surfaces ?? []) surfaceShort.set(s.id, s.short || s.id);
  return { featureLabel, surfaceShort };
}
export function featureLabelOf(maps: LabelMaps, id: string): string { return maps.featureLabel.get(id) ?? id; }
export function surfaceShortOf(maps: LabelMaps, id: string): string { return maps.surfaceShort.get(id) ?? id; }
