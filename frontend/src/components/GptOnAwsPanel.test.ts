/** GPT on AWS 패널 라인 인코딩 순수 로직 (v2.25.1) — 색(리전) × 선 패턴(family) 회귀.
 *
 * model_name 문자열만으로 리전과 family를 되찾는 로직이라, pseudo-region "(US)"가 추가되면
 * "(us-west-2)"와 혼동되거나 GPT 6 Astra가 GPT 5.4로 접히기 쉽다. v2.28.0에서 GPT 6 Sol/Luna가
 * 들어오면서 "GPT 5.6 Sol"의 "6 Sol" 부분 문자열 오인도 고정한다.
 */
import { describe, expect, test } from "vitest";
import type { GptBenchCard, GptBenchTrend, GptBenchTrendPoint } from "@/lib/api";
import {
  FAMILY_DASH, FAMILY_GROUPS, familyOf, groupCardsByFamily, regionOf, toChartData,
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
  test("벤치 6개 family 모두 판별", () => {
    expect(familyOf("OpenAI GPT 6 Astra (Global)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 6 Astra (US)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 6 Astra (us-west-2)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 5.6 Terra (us-east-1)")).toBe("GPT 5.6 Terra");
    expect(familyOf("OpenAI GPT 5.5 (us-east-2)")).toBe("GPT 5.5");
    expect(familyOf("OpenAI GPT 5.4 (us-west-2)")).toBe("GPT 5.4");
  });
  test("GPT 6 Sol/Luna (v2.28.0)", () => {
    expect(familyOf("OpenAI GPT 6 Sol (us-east-1)")).toBe("GPT 6 Sol");
    expect(familyOf("OpenAI GPT 6 Sol (Global)")).toBe("GPT 6 Sol");
    expect(familyOf("OpenAI GPT 6 Sol (US)")).toBe("GPT 6 Sol");
    expect(familyOf("OpenAI GPT 6 Luna (US)")).toBe("GPT 6 Luna");
    expect(familyOf("OpenAI GPT 6 Luna (Global)")).toBe("GPT 6 Luna");
    expect(familyOf("OpenAI GPT 6 Luna (us-east-1)")).toBe("GPT 6 Luna");
  });
  test("GPT 5.6 Sol/Luna는 부분 문자열 \"6 Sol\"/\"6 Luna\"에 걸려 GPT 6로 오인되지 않는다", () => {
    expect(familyOf("OpenAI GPT 5.6 Sol (Global)")).toBe("GPT 5.6 Sol");
    expect(familyOf("OpenAI GPT 5.6 Luna (us-east-1)")).toBe("GPT 5.6 Luna");
  });
  test("라벨 서픽스가 없어도 family만 있으면 판별", () => {
    expect(familyOf("GPT 6 Sol")).toBe("GPT 6 Sol");
    expect(familyOf("OpenAI GPT 5.4")).toBe("GPT 5.4");
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
  test("벤치 family 6종의 선 패턴이 모두 다르다 (실선 = undefined 1종 포함)", () => {
    const families = FAMILY_GROUPS.flatMap((group) => group.families);
    expect(families).toHaveLength(6);
    for (const family of families) expect(family in FAMILY_DASH).toBe(true);
    const patterns = families.map((family) => FAMILY_DASH[family] ?? "solid");
    expect(new Set(patterns).size).toBe(families.length);
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

  test("GPT 6 세대와 GPT 5.x 세대로 나누고 family 열 순서를 고정한다", () => {
    const { groups, other } = groupCardsByFamily([
      card("OpenAI GPT 5.4 (us-east-1)", "GPT 5.4"),
      card("OpenAI GPT 6 Luna (Global)", "GPT 6 Luna"),
      card("OpenAI GPT 6 Sol (US)", "GPT 6 Sol"),
      card("OpenAI GPT 6 Sol (Global)", "GPT 6 Sol"),
      card("OpenAI GPT 5.6 Terra (Global)", "GPT 5.6 Terra"),
    ]);
    expect(groups.map((group) => group.key)).toEqual(["gpt-6", "gpt-5"]);
    expect(groups[0].columns.map((column) => column.family)).toEqual(["GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna"]);
    expect(groups[1].columns.map((column) => column.family)).toEqual(["GPT 5.6 Terra", "GPT 5.5", "GPT 5.4"]);
    // 열 안에서는 입력(API 응답) 순서를 그대로 유지한다 — 여기서 재정렬하지 않는다(US가 Global보다 앞선 입력 그대로).
    expect(groups[0].columns[1].cards.map((c) => c.model_name)).toEqual([
      "OpenAI GPT 6 Sol (US)", "OpenAI GPT 6 Sol (Global)",
    ]);
    expect(groups[0].columns[0].cards).toEqual([]);
    expect(other).toEqual([]);
  });

  test("알 수 없는 family의 카드는 조용히 사라지지 않고 other로 모인다", () => {
    const unknown = card("OpenAI GPT 7 Nova (US)", "GPT 7 Nova");
    const { groups, other } = groupCardsByFamily([unknown, card("OpenAI GPT 5.5 (us-east-2)", "GPT 5.5")]);
    expect(other).toEqual([unknown]);
    const placed = groups.flatMap((group) => group.columns.flatMap((column) => column.cards));
    expect(placed.map((c) => c.model_name)).toEqual(["OpenAI GPT 5.5 (us-east-2)"]);
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
