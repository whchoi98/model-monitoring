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
