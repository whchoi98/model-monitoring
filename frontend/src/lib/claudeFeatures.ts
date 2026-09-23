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
// kind (v2.24.0, 백엔드 D3/RUL-11): "catalog" = 직전 런에 없던 셀, 또는 before/after 중 하나가 사전판정 행(latency_ms IS NULL AND
// error_message IS NULL — 러너가 not_applicable/skipped로 결정; latency 없이 error_message가 있는 행은 프로브 실패라 measured),
// "measured" = 둘 다 프로브 결과. 판별식은 routers/features.py build_latest_payload · engine.change_kind와 동일.
// 구 페이로드에는 없으므로 optional(RUL-4) — 태그·요약 줄은 kind가 있을 때만 렌더.
export type ChangeKind = "catalog" | "measured";
export interface FeatureChange {
  feature: string; surface: string; model_key: string; model_label: string;
  before: FeatureStatus | null; after: FeatureStatus; kind?: ChangeKind;
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

// modelOrder(v2.28.0~): 카탈로그 models[].key 순서. 주면 셀 안 모델 목록(드롭다운, 지연시간 툴팁)을 이 순서로 정렬한다 —
// latest.results는 DB 삽입(프로브 완료) 순이라 모델 순서가 셀마다 달라진다. 모르는 키는 뒤로(안정 정렬), 빈 배열이면 입력 순서 유지.
export function buildGroups(
  features: FeatureDef[], groups: FeatureGroupDef[], surfaces: string[], cells: FeatureCell[],
  lang: string, filter: CellStatus | "all" | "drift", modelKey: string | null = null, modelOrder: readonly string[] = [],
): GroupView[] {
  const rank = new Map(modelOrder.map((k, i) => [k, i]));
  const byModel = (a: FeatureCell, b: FeatureCell) => (rank.get(a.model_key) ?? rank.size) - (rank.get(b.model_key) ?? rank.size);
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
        // D5: 모델 칩 선택 시 그 모델의 셀만 집계 → 단일 셀 배지(N/A·문서상 지원 규칙은 aggregateCell/cellBadge가 그대로 적용)
        const cs = (byKey.get(`${f.id}|${s}`) ?? []).filter((c) => modelKey == null || c.model_key === modelKey);
        if (rank.size) cs.sort(byModel);
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

/** 헬스 카드 헤드라인은 "문서상 제공(GA/Beta) 셀 중 실측 supported 비율"(docHealth — 단위는 피처×모델 셀). 음성 일치(documented=no ∧ unsupported)는
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

/** 런 합계 스트립 (C9): totals의 6 status 키는 합 = 전체 셀(975, v2.28.0~; 이전 780), drift는 verdict 카운트라 status와 겹침 → 별도 필드로 분리. */
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

// ── v2.24.0 — 변경 배너 (D3): kind 요약 + 변경 항목 → 증거 모달용 셀 조회 ─────────────────────────────
export const CHANGE_KIND_LABEL: Record<ChangeKind, { en: string; ko: string }> = {
  catalog: { en: "catalog rule", ko: "카탈로그 규칙" }, measured: { en: "measured", ko: "실측" },
};
export interface ChangeSummary { total: number; catalog: number; measured: number; untagged: number }

export function summarizeChanges(changes: FeatureChange[]): ChangeSummary {
  const out: ChangeSummary = { total: changes.length, catalog: 0, measured: 0, untagged: 0 };
  for (const c of changes) {
    if (c.kind === "catalog") out.catalog += 1;
    else if (c.kind === "measured") out.measured += 1;
    else out.untagged += 1;
  }
  return out;
}

/** 변경 항목(FeatureChange)은 status/documented/verdict가 없어 그대로 모달을 열 수 없다 → latest.results에서 같은 (feature, surface, model_key) 셀을 찾는다. */
export function findCell(cells: FeatureCell[], ref: { feature: string; surface: string; model_key: string }): FeatureCell | null {
  return cells.find((c) => c.feature === ref.feature && c.surface === ref.surface && c.model_key === ref.model_key) ?? null;
}

// ── v2.24.0 — 그룹 접기 (D7): 상태/드리프트 필터가 켜져 있으면 접힘 상태를 무시하고 전부 펼친다 (parity PP:469-470 규칙).
//   collapsed는 "접힌 그룹" Set(펼침 Set이 아님) — 모두 펼치기 = new Set(), 모두 접기 = 모든 g.id.
export function isGroupOpen(filterActive: boolean, collapsed: Set<string>, groupId: string): boolean {
  return filterActive || !collapsed.has(groupId);
}

// ── Key Findings 드로어 파생 (v2.24.0, D4) ──────────────────────────────────────────
// surface 카드 클릭 → verdict 축 6섹션. 셀(모델별 FeatureCell) 단위로 계산하므로 aggregateCell의 대표 모델 접기와 충돌 없음.
// 술어 isProbed/isDocumented는 위(RUL-7)의 단일 정의를 사용한다.
export interface FindingFeatureGroup { feature: string; count: number; probed: number; models: string[]; cells: FeatureCell[] }
export interface FindingChip { feature: string; models: string[]; cells: FeatureCell[] }
export interface ModelDocHealth {
  model_key: string; model_label: string;
  supported: number;         // 문서상 GA/Beta이면서 probed인 셀 중 supported
  probed: number;            // 문서상 GA/Beta이면서 probed인 셀
  docHealth: number | null;  // Math.round(100 * supported / probed), probed === 0 → null (막대 대신 "-")
  drift: number;             // verdict === "drift" 셀 수 (이 모델, 이 surface)
  na_reason: string | null;  // 이 surface에서 모델 미서빙(mantle=null)일 때만 — 막대 대신 사유 표기
}
export interface SurfaceFindings {
  surface: string; total: number;
  drift: FindingFeatureGroup[]; broken: FindingFeatureGroup[];
  intendedGaps: FindingChip[]; undecidedGaps: FindingChip[]; undocumented: FindingChip[];
  perModel: ModelDocHealth[];
}

const MANTLE_NA_EN = "Not measurable — Mantle serves this model only in US GovCloud regions (us-gov-west-1); shown as N/A.";

export function surfaceFindings(cells: FeatureCell[], surface: string, models: ModelDef[], lang: string, modelKey: string | null = null): SurfaceFindings {
  // D5: 모델 칩이 켜져 있으면 셀과 perModel 행을 그 모델로 좁힌다 — 선택되지 않은 모델이 6절에 "문서상 프로브 셀 없음"으로
  // 나열되던 필터 잔상 방지. 패널이 이미 좁힌 visibleCells를 넘겨도 결과는 같다(멱등).
  const own = cells.filter((c) => c.surface === surface && (modelKey == null || c.model_key === modelKey));
  const scopedModels = modelKey == null ? models : models.filter((m) => m.key === modelKey);
  const order = new Map(scopedModels.map((m, i) => [m.key, i]));
  const byModel = (a: FeatureCell, b: FeatureCell) => (order.get(a.model_key) ?? 99) - (order.get(b.model_key) ?? 99);

  const probedByFeature = new Map<string, number>();
  for (const c of own) if (isProbed(c.status)) probedByFeature.set(c.feature, (probedByFeature.get(c.feature) ?? 0) + 1);

  const bucket = (pick: (c: FeatureCell) => boolean): Map<string, FeatureCell[]> => {
    const m = new Map<string, FeatureCell[]>();
    for (const c of own) if (pick(c)) m.set(c.feature, [...(m.get(c.feature) ?? []), c]);
    return m;
  };
  const groups = (pick: (c: FeatureCell) => boolean): FindingFeatureGroup[] =>
    Array.from(bucket(pick).entries())
      .map(([feature, cs]) => {
        const sorted = [...cs].sort(byModel);
        return { feature, count: sorted.length, probed: probedByFeature.get(feature) ?? 0, models: sorted.map((c) => c.model_label), cells: sorted };
      })
      .sort((a, b) => b.count - a.count || a.feature.localeCompare(b.feature));
  const chips = (pick: (c: FeatureCell) => boolean): FindingChip[] =>
    Array.from(bucket(pick).entries()).map(([feature, cs]) => {
      const sorted = [...cs].sort(byModel);
      return { feature, models: sorted.map((c) => c.model_label), cells: sorted };
    });

  const perModel: ModelDocHealth[] = scopedModels.map((m) => {
    let supported = 0, probed = 0, drift = 0;
    for (const c of own) {
      if (c.model_key !== m.key) continue;
      if (c.verdict === "drift") drift += 1;
      if (!isDocumented(c.documented) || !isProbed(c.status)) continue;
      probed += 1;
      if (c.status === "supported") supported += 1;
    }
    const notServed = surface === "mantle" && m.mantle === null;
    return {
      model_key: m.key, model_label: m.label, supported, probed,
      docHealth: probed === 0 ? null : Math.round((100 * supported) / probed), drift,
      na_reason: notServed ? (lang === "en" ? MANTLE_NA_EN : (m.mantle_reason ?? "측정 불가")) : null,
    };
  });

  return {
    surface, total: own.length,
    drift: groups((c) => c.verdict === "drift"),
    broken: groups((c) => c.status === "broken"),
    intendedGaps: chips((c) => c.status === "unsupported" && c.verdict === "match"),
    undecidedGaps: chips((c) => c.status === "unsupported" && c.verdict === "none"),
    undocumented: chips((c) => c.verdict === "undocumented"),
    perModel,
  };
}

// ── v2.24.0 — 모델 칩 (D5): 셀·드리프트·변경 배열을 같은 규칙으로 좁힌다. key null이면 입력 그대로(참조 동일 — useMemo 안정).
export function pickModel<T extends { model_key: string }>(xs: T[], key: string | null): T[] {
  return key ? xs.filter((x) => x.model_key === key) : xs;
}

// ── 지연시간 표시 (v2.24.0, D6) — 값은 프로브 함수 전체 wall-clock(다중 호출 프로브는 합산). 백엔드 변경 없음.
export interface LatencyLine { model_key: string; model_label: string; model_id: string | null; ms: number }

// probed 상태(supported/unsupported/broken/inconclusive)이면서 latency_ms가 있는 행만 — 런타임 not_applicable(extended_thinking 등)이
// latency를 갖는 18셀은 "측정했는데 부적용"으로 읽히므로 제외 (verify-R4 §3-1). isProbed는 위의 단일 정의 (RUL-7).
export function cellLatencyLines(cells: FeatureCell[]): LatencyLine[] {
  return cells
    .filter((c) => isProbed(c.status) && c.latency_ms != null)
    .map((c) => ({ model_key: c.model_key, model_label: c.model_label, model_id: c.model_id, ms: c.latency_ms as number }));
}

const MS_FORMAT = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
// RUL-10. 서브 ms(0.0005~0.0007)는 네트워크 호출 없이 unsupported로 라우팅된 행(_route_or_unsupported) → "<1 ms" (verify-R4 §3-2).
export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return "-";
  if (ms > 0 && ms < 1) return "<1 ms";
  return `${MS_FORMAT.format(Math.round(ms))} ms`;
}

// ── 검증 강도 4종 정의 (v2.24.0, C11) — 행 태그·증거 모달 태그 title, '읽는 법' 5항에서 공유. 출처: ADR-026 결정 1·5·7, catalog.py:110/126/189.
export const VERIFICATION_DESC: Record<"evidence" | "acceptance" | "negative" | "capability", { en: string; ko: string }> = {
  evidence: {
    en: "Evidence: the response content itself is checked (canary round-trip, 2+ stream deltas, cache_read tokens, schema-valid JSON). HTTP 200 alone is never enough.",
    ko: "evidence: 응답 내용 자체를 검사합니다(카나리 왕복, 스트림 델타 2개 이상, cache_read 토큰, 스키마 유효 JSON). HTTP 200만으로는 supported로 두지 않습니다.",
  },
  acceptance: {
    en: "Acceptance: only checks that the request (beta header, parameter) is accepted without error — the feature fires under conditions a short probe cannot force, so no response signal exists.",
    ko: "acceptance: 요청(beta 헤더, 파라미터)이 오류 없이 수락되는지만 확인합니다. 짧은 프로브로는 발동 조건을 만들 수 없어 응답 신호가 없습니다.",
  },
  negative: {
    en: "Negative: additionally sends an invalid value and requires a 400 that names the parameter — separates 'validated' from 'silently ignored'.",
    ko: "negative: 잘못된 값도 함께 보내 해당 파라미터를 지목하는 400 거부를 요구합니다. '검증됨'과 '조용히 무시'를 구분합니다.",
  },
  capability: {
    en: "Capability: read from Models API metadata (e.g. max_input_tokens) instead of a live request — only CP exposes this endpoint.",
    ko: "capability: 실요청 대신 Models API 메타데이터(max_input_tokens 등)를 조회합니다. CP에만 이 엔드포인트가 있습니다.",
  },
};
export function verificationDesc(kind: string, lang: string): string {
  const d = (VERIFICATION_DESC as Record<string, { en: string; ko: string } | undefined>)[kind];
  return d ? (lang === "en" ? d.en : d.ko) : kind;
}
