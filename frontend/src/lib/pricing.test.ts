/**
 * 토큰 단가 유도(backend/pricing.py 미러) 회귀.
 *
 * v2.27.0: GPT 6 Astra는 AWS 공식 모델 카드 단가 반영(In-Region, Geo CRIS $11/$55, Global $10/$50).
 * GPT 6 Sol/Luna 6채널(Global CRIS, US CRIS, us-east-1 인리전)은 AWS offer rate card 단가
 * (2026-09-23 — In-Region, US CRIS Sol $2.20/$11, Luna $0.11/$0.55, Global CRIS Sol $2/$10, Luna $0.10/$0.50).
 * 채널마다 자기 정확 키로 매칭돼야 하고, prefix fallback이 Astra 단가로 조용히 매칭돼서는 안 된다.
 */
import { describe, expect, test } from "vitest";
import { estimateCost, getPricing } from "./pricing";

const GPT6_SOL_LUNA_EXPECTED: [string, { input: number; output: number }][] = [
  ["openai:global:global.openai.gpt-6-sol", { input: 2.0, output: 10.0 }],
  ["openai:us:us.openai.gpt-6-sol", { input: 2.2, output: 11.0 }],
  ["openai:us-east-1:openai.gpt-6-sol", { input: 2.2, output: 11.0 }],
  ["openai:global:global.openai.gpt-6-luna", { input: 0.1, output: 0.5 }],
  ["openai:us:us.openai.gpt-6-luna", { input: 0.11, output: 0.55 }],
  ["openai:us-east-1:openai.gpt-6-luna", { input: 0.11, output: 0.55 }],
];

const GPT6_ASTRA_IDS = [
  "openai:global:global.openai.gpt-6-astra",
  "openai:us:us.openai.gpt-6-astra",
  "openai:us-west-2:openai.gpt-6-astra",
];

describe("getPricing — GPT 6 Sol/Luna offer rate card 단가 (v2.28.0)", () => {
  test.each(GPT6_SOL_LUNA_EXPECTED)("%s → 채널 단가", (id, expected) => {
    expect(getPricing(id)).toEqual(expected);
  });

  test.each(GPT6_SOL_LUNA_EXPECTED)("%s → Astra 단가로 prefix fallback 되지 않는다", (id) => {
    const astraPrices = GPT6_ASTRA_IDS.map((a) => getPricing(a));
    expect(astraPrices.every((p) => p !== null)).toBe(true);
    for (const astra of astraPrices) expect(getPricing(id)).not.toEqual(astra);
  });

  test("estimateCost 산술 — Sol us-east-1 1M/1M = $13.20, Luna Global 2M/500K = $0.45", () => {
    expect(estimateCost("openai:us-east-1:openai.gpt-6-sol", 1_000_000, 1_000_000)).toBeCloseTo(13.2, 9);
    expect(estimateCost("openai:global:global.openai.gpt-6-luna", 2_000_000, 500_000)).toBeCloseTo(0.45, 9);
  });
});

describe("getPricing — GPT 6 Astra 공식 단가 (v2.27.0)", () => {
  test("In-Region, US CRIS는 $11/$55, Global CRIS는 $10/$50", () => {
    expect(getPricing("openai:us-west-2:openai.gpt-6-astra")).toEqual({ input: 11, output: 55 });
    expect(getPricing("openai:us:us.openai.gpt-6-astra")).toEqual({ input: 11, output: 55 });
    expect(getPricing("openai:global:global.openai.gpt-6-astra")).toEqual({ input: 10, output: 50 });
  });
});

describe("getPricing — Claude Opus 5.5 (v2.27.0)", () => {
  test.each([
    "global.anthropic.claude-opus-5-5",
    "us.anthropic.claude-opus-5-5",
    "anthropic:claude-opus-5-5",
  ])("%s → $4/$20 (claude-opus-5 prefix fallback 아님)", (id) => {
    expect(getPricing(id)).toEqual({ input: 4, output: 20 });
  });

  test("Opus 5는 불변", () => {
    expect(getPricing("anthropic:claude-opus-5")).toEqual({ input: 5, output: 25 });
  });
});

describe("getPricing — OpenAI pseudo-region 채널 분리", () => {
  test("Global CRIS는 -global 키로 in-region보다 저렴한 단가", () => {
    expect(getPricing("openai:global:global.openai.gpt-5.6-luna")).toEqual({ input: 0.2, output: 1.2 });
    expect(getPricing("openai:us-east-1:openai.gpt-5.6-luna")).toEqual({ input: 0.22, output: 1.32 });
  });

  test("실제 리전(us-east-1, us-west-2)에는 pseudo-region suffix가 붙지 않는다", () => {
    expect(getPricing("openai:us-west-2:openai.gpt-5.4")).toEqual({ input: 2.75, output: 16.5 });
    expect(getPricing("openai:us-east-2:openai.gpt-5.5")).toEqual({ input: 5.5, output: 33.0 });
  });

  test("1P direct 키도 base 단가로 매칭", () => {
    expect(getPricing("openai:1p:gpt-5.5")).toEqual({ input: 5.5, output: 33.0 });
  });

  test("Bedrock 프로파일, Anthropic CP prefix는 strip", () => {
    expect(getPricing("us.anthropic.claude-fable-5-1")).toEqual({ input: 10, output: 50 });
    expect(getPricing("global.anthropic.claude-sonnet-5")).toEqual({ input: 2, output: 10 });
    expect(getPricing("anthropic:claude-sonnet-5")).toEqual({ input: 2, output: 10 });
  });
});

describe("getPricing — GPT-5.6 Sol 프로모션 단가 (v2.28.1)", () => {
  test("In-Region·Geo $4.40/$22, Global $4/$20 (최소 2026-11-21까지)", () => {
    expect(getPricing("openai:us-east-1:openai.gpt-5.6-sol")).toEqual({ input: 4.4, output: 22 });
    expect(getPricing("openai:us-east-2:openai.gpt-5.6-sol")).toEqual({ input: 4.4, output: 22 });
    expect(getPricing("openai:global:global.openai.gpt-5.6-sol")).toEqual({ input: 4, output: 20 });
  });

  test("Terra, Luna는 변경 없음", () => {
    expect(getPricing("openai:us-east-1:openai.gpt-5.6-terra")).toEqual({ input: 2.2, output: 13.2 });
    expect(getPricing("openai:global:global.openai.gpt-5.6-luna")).toEqual({ input: 0.2, output: 1.2 });
  });
});
