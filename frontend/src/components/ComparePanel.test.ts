/** Comparison Lab 비교 매트릭스 (v2.30.0) — 비용은 /api/pricing `models`의 현재 단가로 계산한다.
 *
 * 단가가 없는 모델은 비용 null("—")이고 최저 비용 강조에서 빠진다. 프런트 단가 미러의 prefix fallback
 * (예: GPT 6 Sol US CRIS가 in-region 단가로 조용히 매칭)은 더 이상 일어나지 않는다.
 */
import { describe, expect, test } from "vitest";
import type { CompareResult } from "@/lib/api";
import type { PricingModelPrice } from "@/lib/types";
import { compareMatrix, type RunningState } from "./ComparePanel";

function run(model_id: string, result: Partial<CompareResult> | null, error?: string): RunningState {
  return {
    model_id, model_name: model_id, text: "",
    result: result === null ? undefined : {
      model_id, model_name: model_id, status: "success", ttft_ms: 500, total_latency_ms: 2000,
      server_latency_ms: null, tps: 50, input_tokens: 1000, output_tokens: 1000, output_text: "", ...result,
    },
    error,
  };
}

const prices: Record<string, PricingModelPrice> = {
  "openai:us-east-1:openai.gpt-6-sol": { input: 2.2, output: 11, verification: "verified" },
  "openai:global:global.openai.gpt-6-luna": { input: 0.1, output: 0.5, verification: "verified" },
};

describe("compareMatrix", () => {
  test("비용은 API 단가로 계산하고 최저 비용은 단가가 있는 모델 중에서 고른다", () => {
    const matrix = compareMatrix([
      run("openai:us-east-1:openai.gpt-6-sol", {}),
      run("openai:global:global.openai.gpt-6-luna", {}),
      run("openai:us:us.openai.gpt-6-sol", {}),
    ], prices)!;
    const cost = Object.fromEntries(matrix.list.map((row) => [row.model_id, row.cost]));
    expect(cost["openai:us-east-1:openai.gpt-6-sol"]).toBeCloseTo(0.0132, 12);
    expect(cost["openai:global:global.openai.gpt-6-luna"]).toBeCloseTo(0.0006, 12);
    expect(cost["openai:us:us.openai.gpt-6-sol"]).toBeNull();
    expect(matrix.bestCost).toBeCloseTo(0.0006, 12);
  });

  test("단가를 못 받았으면 모든 비용이 null이고 최저 비용도 null", () => {
    const matrix = compareMatrix([run("openai:us-east-1:openai.gpt-6-sol", {})], null)!;
    expect(matrix.list[0].cost).toBeNull();
    expect(matrix.bestCost).toBeNull();
  });

  test("성공한 모델만 매트릭스에 들어가고, 하나도 없으면 null", () => {
    const matrix = compareMatrix([
      run("openai:us-east-1:openai.gpt-6-sol", { ttft_ms: 300, tps: 80 }),
      run("openai:global:global.openai.gpt-6-luna", { status: "error" }),
      run("openai:us:us.openai.gpt-6-sol", null, "throttled"),
    ], prices)!;
    expect(matrix.list.map((row) => row.model_id)).toEqual(["openai:us-east-1:openai.gpt-6-sol"]);
    expect(matrix.bestTtft).toBe(300);
    expect(matrix.bestTps).toBe(80);
    expect(compareMatrix([run("openai:us:us.openai.gpt-6-sol", null, "throttled")], prices)).toBeNull();
  });
});
