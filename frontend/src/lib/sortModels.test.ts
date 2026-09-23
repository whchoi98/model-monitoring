import { describe, expect, it } from "vitest";
import { channelRank, familyRank, groupByFamily, isExcludedModel, sortResults } from "./sortModels";

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

// GPT 6 Astra (v2.25.0) — OpenAI 블록 최상단 family + 채널 순서 Global → US → 리전 고정.
describe("sortModels — GPT 6 Astra", () => {
  it("ranks GPT 6 Astra above every GPT 5.x family", () => {
    expect(familyRank("OpenAI GPT 6 Astra (Global)")).toBeLessThan(
      familyRank("OpenAI GPT 5.6 Sol (Global)"),
    );
    expect(familyRank("OpenAI GPT 6 Astra (US)")).toBe(familyRank("OpenAI GPT 6 Astra (us-west-2)"));
  });

  it("orders channels Global → US → region", () => {
    expect(channelRank("OpenAI GPT 6 Astra (Global)")).toBeLessThan(
      channelRank("OpenAI GPT 6 Astra (US)"),
    );
    expect(channelRank("OpenAI GPT 6 Astra (US)")).toBeLessThan(
      channelRank("OpenAI GPT 6 Astra (us-west-2)"),
    );
  });

  // localeCompare tie-break에 맡기면 "(us-west-2)"가 "(US)"보다 먼저 온다(ICU 실측) — 회귀 방지.
  it("sorts the three channels in Global → US → region order and groups them as one family", () => {
    const rows = [
      { model_name: "OpenAI GPT 6 Astra (us-west-2)" },
      { model_name: "OpenAI GPT 5.6 Luna (us-east-1)" },
      { model_name: "OpenAI GPT 6 Astra (US)" },
      { model_name: "OpenAI GPT 6 Astra (Global)" },
    ];
    expect(sortResults(rows).map((r) => r.model_name)).toEqual([
      "OpenAI GPT 6 Astra (Global)",
      "OpenAI GPT 6 Astra (US)",
      "OpenAI GPT 6 Astra (us-west-2)",
      "OpenAI GPT 5.6 Luna (us-east-1)",
    ]);
    expect(groupByFamily(rows).map((g) => g.length)).toEqual([3, 1]);
  });

  it("keeps Bedrock/Anthropic Claude ordering unchanged", () => {
    const rows = [
      { model_name: "Bedrock Claude Fable 5.1 (US)" },
      { model_name: "Bedrock Claude Fable 5.1 (Global)" },
      { model_name: "Anthropic Claude Fable 5.1 (US)" },
    ];
    expect(sortResults(rows).map((r) => r.model_name)).toEqual([
      "Anthropic Claude Fable 5.1 (US)",
      "Bedrock Claude Fable 5.1 (Global)",
      "Bedrock Claude Fable 5.1 (US)",
    ]);
  });

  it("does not hide GPT 6 Astra behind the excluded-family hard filter", () => {
    for (const n of [
      "OpenAI GPT 6 Astra (Global)",
      "OpenAI GPT 6 Astra (US)",
      "OpenAI GPT 6 Astra (us-west-2)",
    ]) {
      expect(isExcludedModel(n)).toBe(false);
    }
  });
});

// Opus 5.5 (v2.27.0) — includes 매칭에서 "Claude Opus 5"가 "Claude Opus 5.5"에 포함되는 접두 충돌 회귀 방지.
describe("sortModels — Opus 5.5 vs Opus 5 family ranking", () => {
  it("ranks Opus 5.5 between Fable 5 and Opus 5, as separate families", () => {
    const r55 = familyRank("Bedrock Claude Opus 5.5 (Global)");
    expect(r55).toBeGreaterThan(familyRank("Bedrock Claude Fable 5 (Global)"));
    expect(r55).toBeLessThan(familyRank("Bedrock Claude Opus 5 (Global)"));
    expect(familyRank("Anthropic Claude Opus 5.5 (US)")).toBe(r55);
  });

  it("groups the three Opus 5.5 channels together, Anthropic first", () => {
    const rows = [
      { model_name: "Bedrock Claude Opus 5 (US)" },
      { model_name: "Bedrock Claude Opus 5.5 (US)" },
      { model_name: "Anthropic Claude Opus 5 (US)" },
      { model_name: "Anthropic Claude Opus 5.5 (US)" },
      { model_name: "Bedrock Claude Opus 5.5 (Global)" },
    ];
    expect(sortResults(rows).map((r) => r.model_name)).toEqual([
      "Anthropic Claude Opus 5.5 (US)",
      "Bedrock Claude Opus 5.5 (Global)",
      "Bedrock Claude Opus 5.5 (US)",
      "Anthropic Claude Opus 5 (US)",
      "Bedrock Claude Opus 5 (US)",
    ]);
    expect(groupByFamily(rows).map((g) => g.length)).toEqual([3, 2]);
  });
});

// GPT 6 Sol / Luna (v2.27.0) — GPT 6 Astra 다음, GPT 5.x보다 위. 채널은 Global → US → us-east-1.
describe("sortModels — GPT 6 Sol / Luna", () => {
  it("orders GPT 6 families Astra → Sol → Luna, all above GPT 5.6 Sol", () => {
    const astra = familyRank("OpenAI GPT 6 Astra (Global)");
    const sol = familyRank("OpenAI GPT 6 Sol (Global)");
    const luna = familyRank("OpenAI GPT 6 Luna (Global)");
    expect(astra).toBeLessThan(sol);
    expect(sol).toBeLessThan(luna);
    expect(luna).toBeLessThan(familyRank("OpenAI GPT 5.6 Sol (Global)"));
  });

  it("sorts each family's three channels Global → US → us-east-1", () => {
    const rows = [
      { model_name: "OpenAI GPT 6 Luna (us-east-1)" },
      { model_name: "OpenAI GPT 6 Sol (us-east-1)" },
      { model_name: "OpenAI GPT 6 Luna (US)" },
      { model_name: "OpenAI GPT 6 Sol (Global)" },
      { model_name: "OpenAI GPT 6 Sol (US)" },
      { model_name: "OpenAI GPT 6 Luna (Global)" },
    ];
    expect(sortResults(rows).map((r) => r.model_name)).toEqual([
      "OpenAI GPT 6 Sol (Global)",
      "OpenAI GPT 6 Sol (US)",
      "OpenAI GPT 6 Sol (us-east-1)",
      "OpenAI GPT 6 Luna (Global)",
      "OpenAI GPT 6 Luna (US)",
      "OpenAI GPT 6 Luna (us-east-1)",
    ]);
    expect(groupByFamily(rows).map((g) => g.length)).toEqual([3, 3]);
  });
});
