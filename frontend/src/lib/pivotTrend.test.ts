/**
 * pivotTrend 회귀·성능 테스트.
 *
 * 2026-07-08: TrendChart의 피벗이 timestamp×model 이중루프 안에서 filtered.find()를
 * 호출하는 O(T×M×N) 구조라, 24h 조회(≈8k행)에서 칩 클릭 한 번에 차트 3개 × 약 6,400만 번
 * 비교가 발생해 메인 스레드가 수 초 멈췄다. Map 기반 O(N) 피벗으로 교체하며 동작을 고정한다.
 */
import { describe, expect, test } from "vitest";
import { pivotTrend } from "./pivotTrend";
import type { TrendPoint } from "./types";

function point(model: string, ts: string, ttft: number | null): TrendPoint {
  return {
    model_id: model.toLowerCase().replace(/\s/g, "-"),
    model_name: model,
    timestamp: ts,
    ttft_ms: ttft,
    total_latency_ms: ttft === null ? null : ttft * 2,
    tps: 40,
    status: "success",
    category: "chat-short",
  };
}

const DATA: TrendPoint[] = [
  point("Model A", "2026-07-08T01:00:00Z", 100),
  point("Model B", "2026-07-08T01:00:00Z", 200),
  point("Model A", "2026-07-08T02:00:00Z", 110),
  // Model B는 02:00 결측 → null로 채워져야 함 (connectNulls용)
  point("Model B", "2026-07-08T03:00:00Z", 230),
];

describe("pivotTrend", () => {
  test("timestamp별 한 행, 모델별 컬럼으로 피벗한다", () => {
    const { modelNames, chartData } = pivotTrend(DATA, "ttft_ms");

    expect(modelNames).toEqual(["Model A", "Model B"]);
    expect(chartData).toHaveLength(3); // 고유 timestamp 3개, 정렬됨
    expect(chartData[0]["Model A"]).toBe(100);
    expect(chartData[0]["Model B"]).toBe(200);
    expect(chartData[1]["Model A"]).toBe(110);
    expect(chartData[1]["Model B"]).toBeNull(); // 결측
    expect(chartData[2]["Model B"]).toBe(230);
    expect(chartData.map((r) => r.timestamp)).toEqual([
      "2026-07-08T01:00:00Z",
      "2026-07-08T02:00:00Z",
      "2026-07-08T03:00:00Z",
    ]);
  });

  test("selectedModels가 있으면 해당 모델만 남긴다", () => {
    const { modelNames, chartData } = pivotTrend(DATA, "ttft_ms", new Set(["Model B"]));

    expect(modelNames).toEqual(["Model B"]);
    // Model B가 없는 timestamp(02:00)는 행 자체가 제거되어야 함
    expect(chartData).toHaveLength(2);
  });

  test("빈 selectedModels(size 0)는 전체 표시와 동일", () => {
    const all = pivotTrend(DATA, "ttft_ms");
    const empty = pivotTrend(DATA, "ttft_ms", new Set());
    expect(empty).toEqual(all);
  });

  test("metric 값이 null인 포인트는 null로 유지된다", () => {
    const { chartData } = pivotTrend([point("Model A", "2026-07-08T01:00:00Z", null)], "ttft_ms");
    expect(chartData[0]["Model A"]).toBeNull();
  });

  test("성능: 168h 규모(56k행, 28모델)를 200ms 안에 피벗한다", () => {
    const big: TrendPoint[] = [];
    for (let t = 0; t < 2016; t++) {
      const ts = new Date(Date.UTC(2026, 5, 1) + t * 300_000).toISOString();
      for (let m = 0; m < 28; m++) {
        big.push(point(`Model ${m}`, ts, 100 + m));
      }
    }
    const start = performance.now();
    const { chartData } = pivotTrend(big, "ttft_ms");
    const elapsed = performance.now() - start;

    expect(chartData).toHaveLength(2016);
    expect(elapsed).toBeLessThan(200); // 구 O(T×M×N) 구현은 수십 초 걸림
  });
});

describe("min–max 밴드 (withRange)", () => {
  const withMinMax: TrendPoint[] = [
    {
      ...point("Model A", "2026-07-08T01:00:00Z", 200),
      ttft_ms_min: 100,
      ttft_ms_max: 300,
    } as TrendPoint,
  ];

  test("withRange: 단일 모델 선택 시 [min,max] 범위 컬럼을 추가한다", () => {
    const { chartData } = pivotTrend(withMinMax, "ttft_ms", new Set(["Model A"]), {
      withRange: true,
    });
    expect(chartData[0]["Model A__range"]).toEqual([100, 300]);
  });

  test("min/max가 없는 원본 행에는 범위 컬럼을 만들지 않는다", () => {
    const { chartData } = pivotTrend(DATA, "ttft_ms", new Set(["Model A"]), {
      withRange: true,
    });
    expect(chartData[0]["Model A__range"]).toBeUndefined();
  });

  test("withRange 미지정이면 범위 컬럼 없음 (기존 동작 유지)", () => {
    const { chartData } = pivotTrend(withMinMax, "ttft_ms", new Set(["Model A"]));
    expect(chartData[0]["Model A__range"]).toBeUndefined();
  });
});
