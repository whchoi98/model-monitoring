/** GPT on AWS 패널 라인 인코딩 순수 로직 (v2.25.1) — 색(리전) × 선 패턴(family) 회귀.
 *
 * model_name 문자열만으로 리전과 family를 되찾는 로직이라, pseudo-region "(US)"가 추가되면
 * "(us-west-2)"와 혼동되거나 GPT 6 Astra가 GPT 5.4로 접히기 쉽다. 그 두 가지를 고정한다.
 */
import { describe, expect, test } from "vitest";
import type { GptBenchTrend, GptBenchTrendPoint } from "@/lib/api";
import { familyOf, regionOf, toChartData } from "./GptOnAwsPanel";

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
  test("4개 family 모두 판별", () => {
    expect(familyOf("OpenAI GPT 6 Astra (Global)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 6 Astra (US)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 6 Astra (us-west-2)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 5.6 Terra (us-east-1)")).toBe("GPT 5.6 Terra");
    expect(familyOf("OpenAI GPT 5.5 (us-east-2)")).toBe("GPT 5.5");
    expect(familyOf("OpenAI GPT 5.4 (us-west-2)")).toBe("GPT 5.4");
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
