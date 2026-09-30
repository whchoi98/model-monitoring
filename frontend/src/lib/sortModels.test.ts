import { describe, expect, it } from "vitest";
import { channelRank, familyRank, groupByFamily, hasAwsRegionSuffix, isExcludedModel, sortByFamily, sortResults } from "./sortModels";

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

// Sonnet 5.5 (v2.32.0) — includes 매칭에서 "Claude Sonnet 5"가 "Claude Sonnet 5.5"에 포함되는 접두 충돌 회귀 방지.
// Sonnet 5.5는 us. 프로파일이 없어 Bedrock Global + CP 2채널이다.
describe("sortModels — Sonnet 5.5 vs Sonnet 5 family ranking", () => {
  it("ranks Sonnet 5.5 between Opus 4.6 and Sonnet 5, as separate families", () => {
    const r55 = familyRank("Bedrock Claude Sonnet 5.5 (Global)");
    expect(r55).toBeGreaterThan(familyRank("Bedrock Claude Opus 4.6 (Global)"));
    expect(r55).toBeLessThan(familyRank("Bedrock Claude Sonnet 5 (Global)"));
    expect(familyRank("Anthropic Claude Sonnet 5.5 (US)")).toBe(r55);
  });

  it("groups Sonnet 5.5 apart from the four Sonnet 5 channels, Anthropic first", () => {
    const rows = [
      { model_name: "Bedrock Claude Sonnet 5 (ap-northeast-2)" },
      { model_name: "Bedrock Claude Sonnet 5 (US)" },
      { model_name: "Bedrock Claude Sonnet 5.5 (Global)" },
      { model_name: "Anthropic Claude Sonnet 5 (US)" },
      { model_name: "Bedrock Claude Sonnet 5 (Global)" },
      { model_name: "Anthropic Claude Sonnet 5.5 (US)" },
    ];
    expect(sortResults(rows).map((r) => r.model_name)).toEqual([
      "Anthropic Claude Sonnet 5.5 (US)",
      "Bedrock Claude Sonnet 5.5 (Global)",
      "Anthropic Claude Sonnet 5 (US)",
      "Bedrock Claude Sonnet 5 (Global)",
      "Bedrock Claude Sonnet 5 (US)",
      "Bedrock Claude Sonnet 5 (ap-northeast-2)",
    ]);
    expect(groupByFamily(rows).map((g) => g.length)).toEqual([2, 4]);
  });
});

// 서울 In-Region (v2.32.0) — "Bedrock <family> (ap-northeast-2)"는 US 티어 뒤 리전 티어(rank 3).
describe("sortModels — Bedrock In-Region (ap-northeast-2)", () => {
  it("puts the lowercase AWS region suffix in the region tier, Bedrock US and Nova stay in the US tier", () => {
    expect(channelRank("Bedrock Claude Opus 5 (ap-northeast-2)")).toBe(3);
    expect(channelRank("Bedrock Claude Sonnet 5 (ap-northeast-2)")).toBe(3);
    expect(channelRank("Bedrock Claude Opus 5 (US)")).toBe(2);
    expect(channelRank("Bedrock Nova 2.0 Lite (US)")).toBe(2);
    expect(channelRank("Bedrock Claude Opus 5 (Global)")).toBe(1);
  });

  // 분기가 없으면 rank 2 동률이 되어 localeCompare가 "(ap-northeast-2)"를 "(US)"보다 앞에 둔다(ICU 실측) — 회귀 방지.
  it("sorts the four Opus 5 channels CP → Global → US → ap-northeast-2", () => {
    const rows = [
      { model_name: "Bedrock Claude Opus 5 (ap-northeast-2)" },
      { model_name: "Bedrock Claude Opus 5 (US)" },
      { model_name: "Bedrock Claude Opus 5 (Global)" },
      { model_name: "Anthropic Claude Opus 5 (US)" },
    ];
    expect(sortResults(rows).map((r) => r.model_name)).toEqual([
      "Anthropic Claude Opus 5 (US)",
      "Bedrock Claude Opus 5 (Global)",
      "Bedrock Claude Opus 5 (US)",
      "Bedrock Claude Opus 5 (ap-northeast-2)",
    ]);
    expect(groupByFamily(rows).map((g) => g.length)).toEqual([4]);
  });
});

// GPT 6.1 Sol (v2.32.0) — OpenAI 블록 최상단 family(GPT 6 Astra 앞). 채널은 Global → US → us-east-1.
describe("sortModels — GPT 6.1 Sol", () => {
  it("ranks GPT 6.1 Sol after Nova and above GPT 6 Astra, apart from GPT 6 Sol", () => {
    const r61 = familyRank("OpenAI GPT 6.1 Sol (Global)");
    expect(r61).toBeGreaterThan(familyRank("Bedrock Nova 2.0 Lite (US)"));
    expect(r61).toBeLessThan(familyRank("OpenAI GPT 6 Astra (Global)"));
    expect(r61).not.toBe(familyRank("OpenAI GPT 6 Sol (Global)"));
  });

  it("sorts the three channels Global → US → us-east-1 as one family", () => {
    const rows = [
      { model_name: "OpenAI GPT 6 Sol (Global)" },
      { model_name: "OpenAI GPT 6.1 Sol (us-east-1)" },
      { model_name: "OpenAI GPT 6.1 Sol (US)" },
      { model_name: "OpenAI GPT 6.1 Sol (Global)" },
    ];
    expect(sortResults(rows).map((r) => r.model_name)).toEqual([
      "OpenAI GPT 6.1 Sol (Global)",
      "OpenAI GPT 6.1 Sol (US)",
      "OpenAI GPT 6.1 Sol (us-east-1)",
      "OpenAI GPT 6 Sol (Global)",
    ]);
    expect(groupByFamily(rows).map((g) => g.length)).toEqual([3, 1]);
  });

  it("does not hide any of the seven new v2.32.0 channels behind the excluded-family hard filter", () => {
    for (const n of [
      "Bedrock Claude Sonnet 5.5 (Global)",
      "Anthropic Claude Sonnet 5.5 (US)",
      "Bedrock Claude Opus 5 (ap-northeast-2)",
      "Bedrock Claude Sonnet 5 (ap-northeast-2)",
      "OpenAI GPT 6.1 Sol (Global)",
      "OpenAI GPT 6.1 Sol (US)",
      "OpenAI GPT 6.1 Sol (us-east-1)",
    ]) {
      expect(isExcludedModel(n)).toBe(false);
    }
  });
});

// 신뢰성 페이지(v2.32.0) — backend가 family를 알파벳순으로 보내 "Claude Sonnet 5"가 "Claude Sonnet 5.5"보다 먼저 왔다.
describe("sortByFamily — reliability family order", () => {
  it("orders family groups like the dashboard, 5.5 before 5 and 5.1 before 5", () => {
    const alphabetical = [
      "Claude Fable 5", "Claude Fable 5.1", "Claude Haiku 4.5", "Claude Opus 5", "Claude Opus 5.5",
      "Claude Sonnet 5", "Claude Sonnet 5.5", "GPT 6 Sol", "GPT 6.1 Sol", "Nova 2.0 Lite",
    ].map((family) => ({ family }));
    expect(sortByFamily(alphabetical).map((group) => group.family)).toEqual([
      "Claude Fable 5.1", "Claude Fable 5", "Claude Opus 5.5", "Claude Opus 5",
      "Claude Sonnet 5.5", "Claude Sonnet 5", "Claude Haiku 4.5", "Nova 2.0 Lite", "GPT 6.1 Sol", "GPT 6 Sol",
    ]);
  });

  it("puts unknown families after the known ones, alphabetically, without mutating the input", () => {
    const groups = [{ family: "Zeta 1" }, { family: "GPT 5.4" }, { family: "Alpha 2" }, { family: "Claude Opus 4.8" }];
    expect(sortByFamily(groups).map((group) => group.family)).toEqual(["Claude Opus 4.8", "GPT 5.4", "Alpha 2", "Zeta 1"]);
    expect(groups[0].family).toBe("Zeta 1");
  });
});

describe("hasAwsRegionSuffix", () => {
  it("matches lower-case AWS region suffixes only", () => {
    expect(hasAwsRegionSuffix("Bedrock Claude Opus 5 (ap-northeast-2)")).toBe(true);
    expect(hasAwsRegionSuffix("OpenAI GPT 5.4 (us-west-2)")).toBe(true);
    for (const name of ["Bedrock Claude Opus 5 (Global)", "Bedrock Claude Opus 5 (US)", "OpenAI GPT 5.4 (1P)", "Anthropic Claude Opus 5 (US)"]) {
      expect(hasAwsRegionSuffix(name)).toBe(false);
    }
  });
});
