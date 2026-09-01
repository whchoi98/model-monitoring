import { describe, expect, it } from "vitest";
import { familyRank, groupByFamily, sortResults } from "./sortModels";

// Fable 5.1 (v2.22.0) — includes 매칭에서 "Claude Fable 5"가 "Claude Fable 5.1"에 포함되는 접두 충돌 회귀 방지.
describe("sortModels — Fable 5.1 vs Fable 5 family ranking", () => {
  it("ranks Fable 5.1 above Fable 5 and keeps them in separate families", () => {
    const r51 = familyRank("Bedrock Claude Fable 5.1 (Global)");
    const r5 = familyRank("Bedrock Claude Fable 5 (Global)");
    expect(r51).toBe(0);
    expect(r5).toBe(1);
    expect(r51).toBeLessThan(r5);
  });

  it("groups the three Fable 5.1 channels together, Anthropic first", () => {
    const rows = [
      { model_name: "Bedrock Claude Fable 5 (US)" },
      { model_name: "Bedrock Claude Fable 5.1 (US)" },
      { model_name: "Anthropic Claude Fable 5.1 (US)" },
      { model_name: "Bedrock Claude Fable 5.1 (Global)" },
      { model_name: "Bedrock Claude Opus 5 (Global)" },
    ];
    const sorted = sortResults(rows).map((r) => r.model_name);
    expect(sorted).toEqual([
      "Anthropic Claude Fable 5.1 (US)",
      "Bedrock Claude Fable 5.1 (Global)",
      "Bedrock Claude Fable 5.1 (US)",
      "Bedrock Claude Fable 5 (US)",
      "Bedrock Claude Opus 5 (Global)",
    ]);
    const groups = groupByFamily(rows);
    expect(groups.map((g) => g.length)).toEqual([3, 1, 1]);
  });
});
