/**
 * 비용 표시 포맷 회귀 (v2.30.0).
 *
 * 프런트 단가 미러(PRICE_TABLE, getPricing, estimateCost)는 없어졌다. 단가는 GET /api/pricing이
 * 단일 출처이고, 호출 비용은 `costFromPrices`(lib/pricingTable.ts)가 그 `models`로 계산한다.
 */
import { describe, expect, test } from "vitest";
import * as pricing from "./pricing";
import { formatCost } from "./pricing";
import { costFromPrices } from "./pricingTable";

describe("formatCost", () => {
  test("null은 대시", () => {
    expect(formatCost(null)).toBe("—");
  });

  test("$0.001 미만은 milli-dollar, $1 미만은 cent, 그 이상은 소수 넷째 자리", () => {
    expect(formatCost(0)).toBe("$0.00m");
    expect(formatCost(0.0005)).toBe("$0.50m");
    expect(formatCost(0.0132)).toBe("$1.32¢");
    expect(formatCost(13.2)).toBe("$13.2000");
    expect(formatCost(168)).toBe("$168.0000");
  });
});

describe("pricing 모듈 — 단가 미러 제거", () => {
  test("formatCost만 export한다", () => {
    expect(Object.keys(pricing).sort()).toEqual(["formatCost"]);
  });
});

describe("costFromPrices + formatCost", () => {
  const models = {
    "openai:us-east-1:openai.gpt-6-sol": { input: 2.2, output: 11, verification: "verified" as const },
  };

  test("API 단가로 계산한 비용을 포맷한다", () => {
    expect(formatCost(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", 1_000_000, 1_000_000))).toBe("$13.2000");
    expect(formatCost(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", 1000, 100))).toBe("$0.33¢");
  });

  test("단가가 없는 모델은 대시", () => {
    expect(formatCost(costFromPrices(models, "global.anthropic.claude-opus-5-5", 1000, 100))).toBe("—");
  });
});
