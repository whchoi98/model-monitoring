/**
 * 토큰 단가 유도(backend/pricing.py 미러) 회귀.
 *
 * v2.27.0: GPT 6 Astra는 AWS 공식 모델 카드 단가 반영(In-Region·Geo CRIS $11/$55, Global $10/$50).
 * GPT 6 Sol/Luna 6채널(Global CRIS, US CRIS, us-east-1 인리전)은 공식 단가 미확정 —
 * PRICE_TABLE에 엔트리가 없어야 하고, prefix fallback이 Astra 등 다른 단가로 조용히 매칭돼서도 안 된다.
 */
import { describe, expect, test } from "vitest";
import { estimateCost, getPricing } from "./pricing";

const GPT6_SOL_LUNA_IDS = ["sol", "luna"].flatMap((fam) => [
  `openai:global:global.openai.gpt-6-${fam}`,
  `openai:us:us.openai.gpt-6-${fam}`,
  `openai:us-east-1:openai.gpt-6-${fam}`,
]);

describe("getPricing — GPT 6 Sol/Luna는 단가 미확정 (v2.27.0)", () => {
  test.each(GPT6_SOL_LUNA_IDS)("%s → null (prefix fallback 매칭 없음)", (id) => {
    expect(getPricing(id)).toBeNull();
    expect(estimateCost(id, 1000, 1000)).toBeNull();
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
