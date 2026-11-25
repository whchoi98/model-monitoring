/** GPT on AWS 패널 라인 인코딩 순수 로직 (v2.25.1) — 색(리전) × 선 패턴(family) 회귀.
 *
 * model_name 문자열만으로 리전과 family를 되찾는 로직이라, pseudo-region "(US)"가 추가되면
 * "(us-west-2)"와 혼동되거나 GPT 6 Astra가 GPT 5.4로 접히기 쉽다. v2.28.0에서 GPT 6 Sol/Luna가
 * 들어오면서 "GPT 5.6 Sol"의 "6 Sol" 부분 문자열 오인도 고정한다. v2.32.0에서 GPT 6.1 Sol이
 * 들어오면서 "GPT 6.1 Solar", "GPT 6.11 Sol" 같은 접두 일치가 6.1 Sol로 판별되지 않는 것도 고정한다.
 * v2.38.0에서 GPT 6.1 Terra가 들어오고 Mantle 인리전이 us-east-1 하나가 됐다 — 지난 사이클의 us-east-2, us-west-2
 * 라벨은 7일 추세에 남으므로 그 리전 판별도 그대로 고정한다.
 * v2.43.0에서 GPT 5.6 Terra와 GPT 5.5를 뺐다(사용자 결정 2026-11-10, ADR-038) — GPT 5.x 세대 묶음이 없어지고, 그 라벨은
 * family ""가 된다(행은 백엔드가 숨긴다).
 * v2.44.0에서 GPT 6.2 Astra와 GPT 6.2 Sol이 들어왔다(사용자 요청 2026-11-17, ADR-039) — GPT 6.x 세대 묶음의 첫 두 열이고,
 * "GPT 6 Astra", "GPT 6 Sol"과 섞이지 않는 것을 고정한다.
 * v2.45.0에서 GPT 5.6 Terra가 돌아왔다(사용자 요청 2026-11-25, ADR-040) — GPT 5.x 세대 묶음이 5.6 Terra 한 열로 다시 생기고,
 * 선 패턴은 예전의 실선(지금은 GPT 6.2 Astra) 대신 비어 있던 파선 "7 4"다. GPT 5.5는 빠진 그대로다.
 */
import { describe, expect, test } from "vitest";
import type { GptBenchCard, GptBenchTrend, GptBenchTrendPoint } from "@/lib/api";
import {
  FAMILY_DASH, FAMILY_GROUPS, familyOf, groupCardsByFamily, legendItemsBelowFold, regionOf, toChartData,
} from "./GptOnAwsPanel";

describe("regionOf", () => {
  test("US CRIS pseudo-region (v2.25.1)", () => {
    expect(regionOf("OpenAI GPT 6 Astra (US)")).toBe("US");
  });
  test("Mantle in-region은 US CRIS와 구분된다", () => {
    expect(regionOf("OpenAI GPT 6 Astra (us-west-2)")).toBe("us-west-2");
    expect(regionOf("OpenAI GPT 5.4 (us-east-1)")).toBe("us-east-1");
    expect(regionOf("OpenAI GPT 5.5 (us-east-2)")).toBe("us-east-2");
  });
  test("Global CRIS", () => {
    expect(regionOf("OpenAI GPT 5.6 Terra (Global)")).toBe("Global");
    expect(regionOf("OpenAI GPT 6 Astra (Global)")).toBe("Global");
  });
  test("리전 표기가 없으면 빈 문자열", () => {
    expect(regionOf("OpenAI GPT 5.4")).toBe("");
  });
});

describe("familyOf", () => {
  test("벤치 GPT 6 Astra와 GPT 5.6 Terra 판별, 모니터링에서 뺀 GPT 5.5, 5.4는 빈 문자열", () => {
    expect(familyOf("OpenAI GPT 6 Astra (Global)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 6 Astra (US)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 6 Astra (us-west-2)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 5.6 Terra (us-east-1)")).toBe("GPT 5.6 Terra");  // "" in v2.43.0~v2.44.x, back in v2.45.0 (ADR-040)
    expect(familyOf("OpenAI GPT 5.5 (us-east-2)")).toBe("");        // v2.43.0
    expect(familyOf("OpenAI GPT 5.4 (us-west-2)")).toBe("");  // v2.39.0: GPT 5.4 left monitoring (ADR-034)
  });
  test("GPT 6 Sol/Luna (v2.28.0)", () => {
    expect(familyOf("OpenAI GPT 6 Sol (us-east-1)")).toBe("GPT 6 Sol");
    expect(familyOf("OpenAI GPT 6 Sol (Global)")).toBe("GPT 6 Sol");
    expect(familyOf("OpenAI GPT 6 Sol (US)")).toBe("GPT 6 Sol");
    expect(familyOf("OpenAI GPT 6 Luna (US)")).toBe("GPT 6 Luna");
    expect(familyOf("OpenAI GPT 6 Luna (Global)")).toBe("GPT 6 Luna");
    expect(familyOf("OpenAI GPT 6 Luna (us-east-1)")).toBe("GPT 6 Luna");
  });
  test("GPT 6.1 Sol (v2.32.0) — Global, US CRIS, us-east-1 3채널", () => {
    expect(familyOf("OpenAI GPT 6.1 Sol (Global)")).toBe("GPT 6.1 Sol");
    expect(familyOf("OpenAI GPT 6.1 Sol (US)")).toBe("GPT 6.1 Sol");
    expect(familyOf("OpenAI GPT 6.1 Sol (us-east-1)")).toBe("GPT 6.1 Sol");
  });
  test("GPT 6.1 Sol과 비슷한 이름은 6.1 Sol로 판별되지 않는다", () => {
    expect(familyOf("OpenAI GPT 6.1 Solar (US)")).toBe("");
    expect(familyOf("OpenAI GPT 6.11 Sol (US)")).toBe("");
  });
  test("GPT 6.1 Terra (v2.38.0) — Global, US CRIS, us-east-1 3채널, GPT 5.6 Terra와 섞이지 않는다", () => {
    expect(familyOf("OpenAI GPT 6.1 Terra (Global)")).toBe("GPT 6.1 Terra");
    expect(familyOf("OpenAI GPT 6.1 Terra (US)")).toBe("GPT 6.1 Terra");
    expect(familyOf("OpenAI GPT 6.1 Terra (us-east-1)")).toBe("GPT 6.1 Terra");
    expect(familyOf("OpenAI GPT 5.6 Terra (Global)")).toBe("GPT 5.6 Terra");  // its own family, never 6.1 Terra
    expect(familyOf("OpenAI GPT 6.1 Terran (US)")).toBe("");
  });
  test("GPT 6.2 Astra, GPT 6.2 Sol (v2.44.0) — Global, US CRIS, us-east-1 3채널, GPT 6 Astra나 GPT 6 Sol로 접히지 않는다", () => {
    for (const channel of ["Global", "US", "us-east-1"]) {
      expect(familyOf(`OpenAI GPT 6.2 Astra (${channel})`)).toBe("GPT 6.2 Astra");
      expect(familyOf(`OpenAI GPT 6.2 Sol (${channel})`)).toBe("GPT 6.2 Sol");
    }
    expect(familyOf("GPT 6.2 Astra")).toBe("GPT 6.2 Astra");
    // 비슷한 이름은 6.2 패밀리가 아니다 — 스펙에 없는 6.2 Luna, 6.2 Terra와 접두 일치
    for (const name of ["OpenAI GPT 6.2 Luna (US)", "OpenAI GPT 6.2 Terra (US)", "OpenAI GPT 6.2 Solar (US)",
      "OpenAI GPT 6.21 Sol (US)", "OpenAI GPT 6.2 Astral (Global)"]) {
      expect(familyOf(name), name).toBe("");
    }
  });
  test("GPT 5.6 Sol/Luna는 부분 문자열 \"6 Sol\"/\"6 Luna\"에 걸려 GPT 6로 오인되지 않는다", () => {
    // GPT 5.6 Sol, Luna는 벤치 대상이 아니다 — 자기 이름으로 읽히고 GPT 6 Sol, GPT 6 Luna로 접히지 않는 것이 요점이다.
    expect(familyOf("OpenAI GPT 5.6 Sol (Global)")).toBe("GPT 5.6 Sol");
    expect(familyOf("OpenAI GPT 5.6 Luna (us-east-1)")).toBe("GPT 5.6 Luna");
    expect("GPT 5.6 Sol" in FAMILY_DASH || "GPT 5.6 Luna" in FAMILY_DASH).toBe(false);
  });
  test("라벨 서픽스가 없어도 family만 있으면 판별", () => {
    expect(familyOf("GPT 6 Sol")).toBe("GPT 6 Sol");
    expect(familyOf("OpenAI GPT 6.1 Terra")).toBe("GPT 6.1 Terra");
  });
  test("모르는 family는 빈 문자열 — 더 이상 GPT 5.4로 접히지 않는다", () => {
    expect(familyOf("OpenAI GPT 7 Nova (us-east-1)")).toBe("");
    expect(familyOf("OpenAI GPT 5.45 (us-east-1)")).toBe("");
    expect(familyOf("OpenAI GPT 6 Solar (US)")).toBe("");
    expect(familyOf("Bedrock Claude Opus 5 (Global)")).toBe("");
    expect(familyOf("")).toBe("");
  });
});

describe("FAMILY_DASH", () => {
  test("벤치 family 8종의 선 패턴이 모두 다르다", () => {
    const families = FAMILY_GROUPS.flatMap((group) => group.families);
    // v2.45.0: GPT 5.6 Terra came back (7 in v2.44.0, when GPT 6.2 Astra and GPT 6.2 Sol joined; 5 in v2.43.0 after GPT 5.6 Terra
    // and GPT 5.5 left, 7 in v2.39.0, 8 in v2.38.0)
    expect(families).toHaveLength(8);
    expect(FAMILY_DASH["GPT 6.2 Astra"]).toBeUndefined();  // 실선 — 키는 있고 값이 없다
    expect(FAMILY_DASH["GPT 6.2 Sol"]).toBe("2 4");
    expect(FAMILY_DASH["GPT 5.6 Terra"]).toBe("7 4");  // 파선 — v2.42.x의 실선은 v2.44.0부터 GPT 6.2 Astra가 쓴다
    for (const retired of ["GPT 5.4", "GPT 5.5"]) expect(retired in FAMILY_DASH).toBe(false);
    for (const family of families) expect(family in FAMILY_DASH).toBe(true);
    const patterns = families.map((family) => FAMILY_DASH[family] ?? "solid");
    expect(new Set(patterns).size).toBe(families.length);
  });
  test("모든 패턴의 한 주기가 범례 스와치 선(38px) 안에 들어간다", () => {
    for (const pattern of Object.values(FAMILY_DASH)) {
      if (!pattern) continue;
      const period = pattern.split(" ").map(Number).reduce((a, b) => a + b, 0);
      expect(period).toBeLessThanOrEqual(38);
    }
  });
  test("모르는 family(\"\")는 패턴이 없어 실선", () => {
    expect(FAMILY_DASH[familyOf("OpenAI GPT 7 Nova (US)")]).toBeUndefined();
  });
});

describe("groupCardsByFamily", () => {
  const card = (model_name: string, family: string): GptBenchCard => ({
    model_id: model_name, model_name, family, region: regionOf(model_name), runs: 10, success: 10,
    median_ttfb_ms: 800, median_ttft_ms: 1800, median_gap_ms: 1000, p95_ttft_ms: 2200,
    cache_hit_rate: 1, median_reasoning_tokens: 40, last_error: null,
  });

  test("GPT 6.x 세대와 GPT 5.x 세대로 묶고 family 열 순서를 고정한다 (GPT 5.x 묶음은 v2.43.0에 뺐다가 v2.45.0에 5.6 Terra로 돌아왔다)", () => {
    const { groups, other } = groupCardsByFamily([
      card("OpenAI GPT 6 Luna (Global)", "GPT 6 Luna"),
      card("OpenAI GPT 6 Sol (US)", "GPT 6 Sol"),
      card("OpenAI GPT 5.6 Terra (us-east-1)", "GPT 5.6 Terra"),
      card("OpenAI GPT 6 Sol (Global)", "GPT 6 Sol"),
      card("OpenAI GPT 5.6 Terra (Global)", "GPT 5.6 Terra"),
    ]);
    expect(groups.map((group) => group.key)).toEqual(["gpt-6", "gpt-5"]);
    expect(groups.map((group) => [group.en, group.ko])).toEqual(
      [["GPT 6.x generation", "GPT 6.x 세대"], ["GPT 5.x generation", "GPT 5.x 세대"]]);
    expect(groups[1].columns.map((column) => column.family)).toEqual(["GPT 5.6 Terra"]);
    expect(groups[1].columns[0].cards.map((c) => c.model_name)).toEqual(
      ["OpenAI GPT 5.6 Terra (us-east-1)", "OpenAI GPT 5.6 Terra (Global)"]);
    expect(groups[0].columns.map((column) => column.family)).toEqual(
      ["GPT 6.2 Astra", "GPT 6.2 Sol", "GPT 6.1 Sol", "GPT 6.1 Terra", "GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna"]);
    // 열 안에서는 입력(API 응답) 순서를 그대로 유지한다 — 여기서 재정렬하지 않는다(US가 Global보다 앞선 입력 그대로).
    expect(groups[0].columns[5].cards.map((c) => c.model_name)).toEqual([
      "OpenAI GPT 6 Sol (US)", "OpenAI GPT 6 Sol (Global)",
    ]);
    for (const index of [0, 1, 2, 3, 4]) expect(groups[0].columns[index].cards).toEqual([]);
    expect(other).toEqual([]);
  });

  test("GPT 6.2 Astra, GPT 6.2 Sol 카드는 GPT 6.x 세대 첫 두 열에 모인다 (v2.44.0)", () => {
    const { groups, other } = groupCardsByFamily([
      card("OpenAI GPT 6 Astra (Global)", "GPT 6 Astra"),
      card("OpenAI GPT 6.2 Sol (Global)", "GPT 6.2 Sol"),
      card("OpenAI GPT 6.2 Astra (Global)", "GPT 6.2 Astra"),
      card("OpenAI GPT 6.2 Astra (US)", "GPT 6.2 Astra"),
      card("OpenAI GPT 6.2 Astra (us-east-1)", "GPT 6.2 Astra"),
      card("OpenAI GPT 6 Sol (Global)", "GPT 6 Sol"),
    ]);
    expect(groups[0].columns.slice(0, 2).map((column) => column.family)).toEqual(["GPT 6.2 Astra", "GPT 6.2 Sol"]);
    expect(groups[0].columns[0].cards.map((c) => c.model_name)).toEqual([
      "OpenAI GPT 6.2 Astra (Global)", "OpenAI GPT 6.2 Astra (US)", "OpenAI GPT 6.2 Astra (us-east-1)",
    ]);
    expect(groups[0].columns[1].cards.map((c) => c.model_name)).toEqual(["OpenAI GPT 6.2 Sol (Global)"]);
    // 이름이 비슷한 GPT 6 Astra, GPT 6 Sol은 자기 열에 그대로 있다
    expect(groups[0].columns[4].cards.map((c) => c.model_name)).toEqual(["OpenAI GPT 6 Astra (Global)"]);
    expect(groups[0].columns[5].cards.map((c) => c.model_name)).toEqual(["OpenAI GPT 6 Sol (Global)"]);
    expect(other).toEqual([]);
  });

  test("GPT 6.1 Sol 카드는 GPT 6.2 다음 열에 모인다 (v2.32.0, v2.43.x까지 첫 열)", () => {
    const { groups, other } = groupCardsByFamily([
      card("OpenAI GPT 6 Sol (Global)", "GPT 6 Sol"),
      card("OpenAI GPT 6.1 Sol (Global)", "GPT 6.1 Sol"),
      card("OpenAI GPT 6.1 Sol (US)", "GPT 6.1 Sol"),
      card("OpenAI GPT 6.1 Sol (us-east-1)", "GPT 6.1 Sol"),
    ]);
    expect(groups[0].columns[2].cards.map((c) => c.model_name)).toEqual([
      "OpenAI GPT 6.1 Sol (Global)", "OpenAI GPT 6.1 Sol (US)", "OpenAI GPT 6.1 Sol (us-east-1)",
    ]);
    expect(groups[0].columns[5].cards.map((c) => c.model_name)).toEqual(["OpenAI GPT 6 Sol (Global)"]);
    expect(other).toEqual([]);
  });

  test("GPT 6.1 Terra 카드는 GPT 6.1 Sol 다음 열에 모인다 (v2.38.0)", () => {
    const { groups, other } = groupCardsByFamily([
      card("OpenAI GPT 6 Astra (Global)", "GPT 6 Astra"),
      card("OpenAI GPT 6.1 Terra (Global)", "GPT 6.1 Terra"),
      card("OpenAI GPT 6.1 Terra (US)", "GPT 6.1 Terra"),
      card("OpenAI GPT 6.1 Terra (us-east-1)", "GPT 6.1 Terra"),
    ]);
    expect(groups[0].columns[3].family).toBe("GPT 6.1 Terra");
    expect(groups[0].columns[3].cards.map((c) => c.model_name)).toEqual([
      "OpenAI GPT 6.1 Terra (Global)", "OpenAI GPT 6.1 Terra (US)", "OpenAI GPT 6.1 Terra (us-east-1)",
    ]);
    expect(groups[0].columns[4].cards.map((c) => c.model_name)).toEqual(["OpenAI GPT 6 Astra (Global)"]);
    expect(other).toEqual([]);
  });

  test("알 수 없는 family의 카드는 조용히 사라지지 않고 other로 모인다", () => {
    const unknown = card("OpenAI GPT 7 Nova (US)", "GPT 7 Nova");
    const { groups, other } = groupCardsByFamily([unknown, card("OpenAI GPT 6 Luna (us-east-1)", "GPT 6 Luna")]);
    expect(other).toEqual([unknown]);
    const placed = groups.flatMap((group) => group.columns.flatMap((column) => column.cards));
    expect(placed.map((c) => c.model_name)).toEqual(["OpenAI GPT 6 Luna (us-east-1)"]);
  });
});

describe("toChartData", () => {
  const firstChannel = "OpenAI GPT 6 Astra (US)";
  const secondChannel = "OpenAI GPT 6 Astra (Global)";
  const firstPoint: GptBenchTrendPoint = {
    cycle_ts: "2026-09-22T10:00:00",
    median_ttfb_ms: 0, median_ttft_ms: 1000, median_gap_ms: 1000, errors: 0,
  };
  const recoveredPoint: GptBenchTrendPoint = {
    cycle_ts: "2026-09-22T11:00:00Z",
    median_ttfb_ms: 100, median_ttft_ms: 1200, median_gap_ms: 1100, errors: 0,
  };
  const trendWith = (points: GptBenchTrendPoint[]): GptBenchTrend => ({
    hours: 3,
    series: [
      { model_id: "astra-us", model_name: firstChannel, points },
      { model_id: "astra-global", model_name: secondChannel, points },
    ],
  });

  test.each([
    ["median_ttfb_ms", 0, 100],
    ["median_ttft_ms", 1000, 1200],
    ["median_gap_ms", 1000, 1100],
  ] as const)("breaks %s across an hour with no collected cycles", (metric, before, after) => {
    const { rows, names } = toChartData(trendWith([recoveredPoint, firstPoint]), metric);
    const start = Date.parse("2026-09-22T10:00:00Z");
    const end = Date.parse("2026-09-22T11:00:00Z");

    expect(names).toEqual([firstChannel, secondChannel]);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toEqual({ ts: start, [firstChannel]: before, [secondChannel]: before });
    expect(rows[2]).toEqual({ ts: end, [firstChannel]: after, [secondChannel]: after });
    expect(rows[1].ts).toBeGreaterThan(start);
    expect(rows[1].ts).toBeLessThan(end);
    expect(rows[1][firstChannel]).toBeNull();
    expect(rows[1][secondChannel]).toBeNull();
  });

  test.each([
    ["15-minute cadence", "2026-09-22T10:15:00Z", 2],
    ["30-minute grace boundary", "2026-09-22T10:30:00Z", 2],
    ["just beyond the grace period", "2026-09-22T10:30:00.001Z", 3],
  ] as const)("respects the %s", (_label, cycle_ts, expectedRows) => {
    const { rows } = toChartData(trendWith([firstPoint, { ...recoveredPoint, cycle_ts }]), "median_ttft_ms");
    expect(rows).toHaveLength(expectedRows);
  });

  test("retains partial-success medians, real zeroes and explicit failed cycles", () => {
    const { rows } = toChartData(trendWith([
      { ...firstPoint, errors: 2 },
      {
        cycle_ts: "2026-09-22T10:15:00Z",
        median_ttfb_ms: null, median_ttft_ms: null, median_gap_ms: null, errors: 10,
      },
      { ...recoveredPoint, cycle_ts: "2026-09-22T10:30:00Z", errors: 1 },
    ]), "median_ttfb_ms");

    expect(rows).toEqual([
      { ts: Date.parse("2026-09-22T10:00:00Z"), [firstChannel]: 0, [secondChannel]: 0 },
      { ts: Date.parse("2026-09-22T10:15:00Z"), [firstChannel]: null, [secondChannel]: null },
      { ts: Date.parse("2026-09-22T10:30:00Z"), [firstChannel]: 100, [secondChannel]: 100 },
    ]);
  });
});

describe("legendItemsBelowFold — 휴대폰 범례의 숨은 항목 수 안내", () => {
  // 한 줄 17px + 간격 8px, 보이는 높이 144px(max-h-36) — 390px 화면의 실측 배치
  const rows = (count: number, perRow = 1) =>
    Array.from({ length: count }, (_, index) => ({ top: 4 + Math.floor(index / perRow) * 25, height: 17 }));

  test("18개 중 보이는 영역 아래 항목만 센다", () => {
    expect(legendItemsBelowFold(rows(18), 0, 144)).toBe(12);
  });
  test("끝까지 스크롤하면 0", () => {
    expect(legendItemsBelowFold(rows(18), 18 * 25 - 144, 144)).toBe(0);
  });
  test("세로 중심 기준 — 절반 넘게 잘린 항목은 숨은 것으로 센다", () => {
    expect(legendItemsBelowFold([{ top: 130, height: 17 }], 0, 144)).toBe(0);
    expect(legendItemsBelowFold([{ top: 137, height: 17 }], 0, 144)).toBe(1);
  });
  test("한 행에 여러 항목이 있으면 각각 센다, 넘치지 않으면 0", () => {
    expect(legendItemsBelowFold(rows(18, 3), 0, 144)).toBe(0);
    expect(legendItemsBelowFold(rows(18, 2), 0, 144)).toBe(6);
  });
});
