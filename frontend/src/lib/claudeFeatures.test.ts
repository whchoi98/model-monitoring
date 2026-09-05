/** Claude API Features 매트릭스 순수 로직 (v2.23.0) — 셀 집계·그룹 구성·헬스 계산 회귀 */
import { describe, expect, test } from "vitest";
import { aggregateCell, buildGroups, surfaceHealth, type FeatureCell, type FeatureDef } from "./claudeFeatures";

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
});

describe("surfaceHealth", () => {
  test("health = supported / (supported + broken)", () => {
    const h = surfaceHealth([cell({}), cell({ status: "broken" }), cell({ status: "unsupported" })], "cp");
    expect(h).toEqual({ supported: 1, broken: 1, health: 50 });
  });
});
