/** Claude API Features 매트릭스 순수 로직 (v2.23.0) — 셀 집계·그룹 구성·헬스 계산 회귀 */
import { describe, expect, test } from "vitest";
import {
  aggregateCell, buildGroups, featureLabelOf, findCell, formatDuration, isDocumented, isGroupOpen, isProbed, labelMaps, runSummary,
  summarizeChanges, surfaceHealth, surfaceShortOf, surfaceSummary, visibleSegments,
  type FeatureCell, type FeatureChange, type FeatureDef,
} from "./claudeFeatures";

const cell = (p: Partial<FeatureCell>): FeatureCell => ({
  feature: "f", surface: "cp", model_key: "opus-5", model_label: "Opus 5", model_id: "claude-opus-5",
  status: "supported", documented: "ga", verdict: "match", latency_ms: 1, ...p,
});

describe("aggregateCell", () => {
  test("all supported → supported", () => {
    expect(aggregateCell([cell({}), cell({ model_key: "sonnet-5" })]).status).toBe("supported");
  });
  test("broken wins", () => {
    expect(aggregateCell([cell({}), cell({ status: "broken", verdict: "drift" })]).status).toBe("broken");
  });
  test("mixed supported/unsupported → partial", () => {
    expect(aggregateCell([cell({}), cell({ status: "unsupported", verdict: "drift" })]).status).toBe("partial");
  });
  test("only not_applicable → not_applicable; empty → empty", () => {
    expect(aggregateCell([cell({ status: "not_applicable", verdict: "none" })]).status).toBe("not_applicable");
    expect(aggregateCell([]).status).toBe("empty");
  });
  test("all unsupported → unsupported; all inconclusive → inconclusive", () => {
    expect(aggregateCell([cell({ status: "unsupported", verdict: "drift" }), cell({ status: "unsupported", verdict: "drift", model_key: "sonnet-5" })]).status).toBe("unsupported");
    expect(aggregateCell([cell({ status: "inconclusive", verdict: "none" })]).status).toBe("inconclusive");
  });
  test("only skipped (no not_applicable) → skipped", () => {
    expect(aggregateCell([cell({ status: "skipped", verdict: "none" })]).status).toBe("skipped");
  });
});

describe("buildGroups", () => {
  const features: FeatureDef[] = [
    { id: "a", group: "core", label_ko: "가", label_en: "A", desc_ko: "", desc_en: "", doc_url: "u",
      documented: { cp: "ga", mantle: "ga" }, verification: "evidence", notes: "" },
    { id: "b", group: "model", label_ko: "나", label_en: "B", desc_ko: "", desc_en: "", doc_url: "u",
      documented: { cp: "no", mantle: "no" }, verification: "acceptance", notes: "" },
  ];
  const groups = [{ id: "core", label_ko: "코어", label_en: "Core" }, { id: "model", label_ko: "모델", label_en: "Model" }];
  const cells = [cell({ feature: "a" }), cell({ feature: "a", surface: "mantle", status: "broken", verdict: "drift" }),
                 cell({ feature: "b", status: "unsupported", documented: "no", verdict: "match" })];

  test("groups keep catalog order and aggregate per surface", () => {
    const g = buildGroups(features, groups, ["cp", "mantle"], cells, "ko", "all");
    expect(g.map((x) => x.id)).toEqual(["core", "model"]);
    expect(g[0].rows[0].label).toBe("가");
    expect(g[0].rows[0].cells.cp.status).toBe("supported");
    expect(g[0].rows[0].cells.mantle.status).toBe("broken");
    expect(g[1].rows[0].cells.mantle.status).toBe("empty");
  });
  test("status filter hides rows without a matching cell", () => {
    const g = buildGroups(features, groups, ["cp", "mantle"], cells, "en", "broken");
    expect(g.map((x) => x.id)).toEqual(["core"]);
  });
  test("drift filter keeps only rows with drift cells and counts them", () => {
    const g = buildGroups(features, groups, ["cp", "mantle"], cells, "ko", "drift");
    expect(g.map((x) => x.id)).toEqual(["core"]);
    expect(g[0].rows[0].drift).toBe(1);
  });
});

describe("surfaceHealth", () => {
  test("health = supported / (supported + broken)", () => {
    const h = surfaceHealth([cell({}), cell({ status: "broken" }), cell({ status: "unsupported" })], "cp");
    expect(h).toEqual({ supported: 1, broken: 1, health: 50 });
  });
});

describe("surfaceSummary (v2.24.0 헬스 카드)", () => {
  // Mantle run #3 축소판 — surface "mantle"만 집계, "cp" 셀은 무시돼야 함
  const mantle = (p: Partial<FeatureCell>) => cell({ surface: "mantle", ...p });
  const cells: FeatureCell[] = [
    mantle({ feature: "a" }),                                                            // ga supported
    mantle({ feature: "b", documented: "beta" }),                                        // beta supported
    mantle({ feature: "c", status: "unsupported", verdict: "drift" }),                   // ga unsupported → drift
    mantle({ feature: "d", status: "unsupported", documented: "no", verdict: "match" }), // 음성 일치(문서 미제공, 실측 미지원)
    mantle({ feature: "e", status: "unsupported", documented: "no", verdict: "match" }),
    mantle({ feature: "f", status: "skipped", verdict: "none" }),                        // ga skipped → 문서상 지원(sky)
    mantle({ feature: "g", status: "not_applicable", documented: "no", verdict: "none" }),
    mantle({ feature: "h", status: "not_applicable", documented: "no", verdict: "none" }),
    mantle({ feature: "i", status: "inconclusive", documented: "unknown", verdict: "none" }),
    mantle({ feature: "j", documented: "no", verdict: "undocumented" }),                 // 문서 미제공인데 동작
    cell({ feature: "z", status: "broken", verdict: "drift" }),                          // surface cp → 제외
  ];
  test("total/counts/segments cover ALL cells of the surface (N/A included)", () => {
    const s = surfaceSummary(cells, "mantle");
    expect(s.total).toBe(10);
    expect(s.counts).toEqual({ supported: 3, unsupported: 3, broken: 0, inconclusive: 1, skipped: 1, not_applicable: 2 });
    expect(s.segments).toEqual({ supported: 3, unsupported: 3, broken: 0, inconclusive: 1, documented_only: 1, other: 2 });
    expect(s.probed).toBe(7);
    expect(s.drift).toBe(1);
    expect(s.undocumented).toBe(1);
  });
  test("docHealth = documented(ga/beta) ∧ supported / documented ∧ probed — negative matches do not inflate it", () => {
    const s = surfaceSummary(cells, "mantle");
    expect(s.docSupported).toBe(2); // a, b
    expect(s.docProbed).toBe(3);    // a, b, c — i(unknown), d/e(documented=no) 제외
    expect(s.docHealth).toBe(67);
    const withoutNegatives = surfaceSummary(cells.filter((c) => c.feature !== "d" && c.feature !== "e"), "mantle");
    expect(withoutNegatives.docHealth).toBe(67);
  });
  test("legacy fields stay identical to surfaceHealth()", () => {
    const s = surfaceSummary(cells, "mantle");
    const h = surfaceHealth(cells, "mantle");
    expect({ supported: s.supported, broken: s.broken, health: s.health }).toEqual(h);
    expect(h).toEqual({ supported: 3, broken: 0, health: 100 });
  });
  test("no documented+probed cell → docHealth null (card shows '-'); empty surface → total 0", () => {
    const onlyNa = [mantle({ status: "not_applicable", verdict: "none" }), mantle({ status: "skipped", verdict: "none", model_key: "sonnet-5" })];
    const s = surfaceSummary(onlyNa, "mantle");
    expect(s.docHealth).toBeNull();
    expect(s.total).toBe(2);
    expect(s.segments.documented_only).toBe(1);
    expect(s.segments.other).toBe(1);
    expect(surfaceSummary([], "mantle")).toMatchObject({ total: 0, docHealth: null, drift: 0, health: 0 });
  });
  test("visibleSegments: supported/unsupported/broken always, the other three only when > 0 (RUL-5); shared predicates", () => {
    expect(visibleSegments(surfaceSummary(cells, "mantle"))).toEqual(["supported", "unsupported", "broken", "inconclusive", "documented_only", "other"]);
    expect(visibleSegments(surfaceSummary([mantle({ feature: "a" })], "mantle"))).toEqual(["supported", "unsupported", "broken"]);
    expect(visibleSegments(surfaceSummary([mantle({ status: "not_applicable", verdict: "none" })], "mantle"))).toEqual(["supported", "unsupported", "broken", "other"]);
    expect(isProbed("inconclusive")).toBe(true);
    expect(isProbed("skipped")).toBe(false);
    expect(isProbed("not_applicable")).toBe(false);
    expect(isDocumented("beta")).toBe(true);
    expect(isDocumented("unknown")).toBe(false);
    expect(isDocumented("no")).toBe(false);
  });
});

describe("runSummary / formatDuration (v2.24.0 런 합계 스트립)", () => {
  test("totals → 6 status counts in fixed order, total = their sum, drift kept separate", () => {
    const s = runSummary({ supported: 419, unsupported: 206, broken: 0, inconclusive: 0, skipped: 15, not_applicable: 140, drift: 25 });
    expect(s).not.toBeNull();
    expect(s!.total).toBe(780);
    expect(s!.statuses.map((x) => x.status)).toEqual(["supported", "unsupported", "broken", "inconclusive", "skipped", "not_applicable"]);
    expect(s!.statuses[0].count).toBe(419);
    expect(s!.drift).toBe(25);
  });
  test("missing keys count as 0; null/undefined totals → null", () => {
    expect(runSummary({ supported: 1 })!.total).toBe(1);
    expect(runSummary({ supported: 1 })!.drift).toBe(0);
    expect(runSummary(null)).toBeNull();
    expect(runSummary(undefined)).toBeNull();
  });
  test("formatDuration: run #3 → '6분 15초' / '6m 15s'; seconds only under a minute; null when missing or reversed", () => {
    expect(formatDuration("2026-09-06T00:26:35.455128+00:00", "2026-09-06T00:32:50.794359+00:00", "ko")).toBe("6분 15초");
    expect(formatDuration("2026-09-06T00:26:35.455128+00:00", "2026-09-06T00:32:50.794359+00:00", "en")).toBe("6m 15s");
    expect(formatDuration("2026-09-06T00:00:00Z", "2026-09-06T00:00:42Z", "ko")).toBe("42초");
    expect(formatDuration(null, "2026-09-06T00:32:50Z", "ko")).toBeNull();
    expect(formatDuration("2026-09-06T00:32:50Z", "2026-09-06T00:26:35Z", "ko")).toBeNull();
  });
});

describe("cellBadge", () => {
  test("skipped + documented GA/Beta → '문서상 지원' (sky), not measured", async () => {
    const { cellBadge, DOCUMENTED_ONLY_STYLE, STATUS_LABEL, STATUS_STYLE } = await import("./claudeFeatures");
    expect(cellBadge("skipped", "ga", "ko")).toEqual({ label: "문서상 지원", style: DOCUMENTED_ONLY_STYLE, documentedOnly: true });
    expect(cellBadge("skipped", "beta", "en").label).toBe("Documented");
    // 문서상 미제공/unknown이면 그대로 Skipped
    expect(cellBadge("skipped", "no", "ko")).toEqual({ label: STATUS_LABEL.skipped, style: STATUS_STYLE.skipped, documentedOnly: false });
    // 측정된 상태는 영향 없음
    expect(cellBadge("supported", "ga", "ko").label).toBe(STATUS_LABEL.supported);
    expect(cellBadge("not_applicable", "ga", "ko").label).toBe(STATUS_LABEL.not_applicable);
  });
});

describe("labelMaps (v2.24.0 — 카탈로그 단일 출처 라벨)", () => {
  const catalog = {
    features: [
      { id: "a", group: "core", label_ko: "가", label_en: "A", desc_ko: "", desc_en: "", doc_url: "u", documented: {}, verification: "evidence", notes: "" },
      { id: "b", group: "core", label_ko: "", label_en: "", desc_ko: "", desc_en: "", doc_url: "u", documented: {}, verification: "evidence", notes: "" },
    ] as FeatureDef[],
    surfaces: [{ id: "bedrock_messages", label: "Bedrock runtime · Messages API", short: "Messages API", group: "bedrock", region: "us-east-1" }],
  };
  test("ko/en feature labels and surface short names from the catalog; empty label falls back to id", () => {
    const ko = labelMaps(catalog, "ko");
    expect(featureLabelOf(ko, "a")).toBe("가");
    expect(featureLabelOf(labelMaps(catalog, "en"), "a")).toBe("A");
    expect(featureLabelOf(ko, "b")).toBe("b");
    expect(surfaceShortOf(ko, "bedrock_messages")).toBe("Messages API");
  });
  test("unknown id and null catalog fall back to the raw id (catalog not loaded yet)", () => {
    expect(featureLabelOf(labelMaps(catalog, "ko"), "zzz")).toBe("zzz");
    const empty = labelMaps(null, "ko");
    expect(featureLabelOf(empty, "a")).toBe("a");
    expect(surfaceShortOf(empty, "mantle")).toBe("mantle");
  });
});

describe("summarizeChanges / findCell (v2.24.0 변경 배너)", () => {
  const ch = (p: Partial<FeatureChange>): FeatureChange => ({
    feature: "f", surface: "cp", model_key: "opus-5", model_label: "Opus 5", before: "unsupported", after: "not_applicable", ...p,
  });
  test("counts catalog / measured / untagged (kind absent on pre-v2.24 payloads)", () => {
    expect(summarizeChanges([ch({ kind: "catalog" }), ch({ kind: "catalog", model_key: "sonnet-5" }), ch({ kind: "measured", feature: "g" }), ch({ feature: "h" })]))
      .toEqual({ total: 4, catalog: 2, measured: 1, untagged: 1 });
    expect(summarizeChanges([])).toEqual({ total: 0, catalog: 0, measured: 0, untagged: 0 });
  });
  test("findCell resolves a change to its result cell by (feature, surface, model_key); null when absent", () => {
    const cells = [
      cell({ feature: "f", surface: "cp", model_key: "opus-5" }),
      cell({ feature: "f", surface: "cp", model_key: "sonnet-5", status: "unsupported", verdict: "drift" }),
    ];
    expect(findCell(cells, ch({ model_key: "sonnet-5" }))?.status).toBe("unsupported");
    expect(findCell(cells, ch({ model_key: "opus-5" }))?.status).toBe("supported");
    expect(findCell(cells, ch({ surface: "mantle" }))).toBeNull();
  });
});

describe("isGroupOpen (v2.24.0 — 필터 활성 시 강제 펼침)", () => {
  test("no filter: open unless the user collapsed the group", () => {
    const collapsed = new Set(["model"]);
    expect(isGroupOpen(false, collapsed, "core")).toBe(true);
    expect(isGroupOpen(false, collapsed, "model")).toBe(false);
  });
  test("active filter forces every group open, even one collapsed earlier (collapse → drift filter regression)", () => {
    expect(isGroupOpen(true, new Set(["model"]), "model")).toBe(true);
    expect(isGroupOpen(true, new Set(), "core")).toBe(true);
  });
});
