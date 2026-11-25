/** 수동 프로브 스트림 카드 라벨 (v2.32.0) — SSE 키(model_id:iteration)에서 채널 표기를 되찾는 순수 로직.
 *
 * 서울 In-Region 키(bedrock:<region>:<fm id>)는 ":"가 여러 번 들어가고, Sonnet 5.5("sonnet-5-5")와
 * GPT 6.1 Sol("gpt-6.1-sol")은 기존 family와 부분 문자열로 겹치기 쉬워 회귀를 고정한다.
 */
import { describe, expect, test } from "vitest";
import { extractModelName } from "./StreamingView";

const name = (key: string) => extractModelName(key, new Map());

describe("extractModelName", () => {
  test("Bedrock In-Region 키는 리전 서픽스", () => {
    expect(name("bedrock:ap-northeast-2:anthropic.claude-opus-5:1")).toBe("Claude Opus 5 (ap-northeast-2)");
    expect(name("bedrock:ap-northeast-2:anthropic.claude-sonnet-5:1")).toBe("Claude Sonnet 5 (ap-northeast-2)");
  });
  test("Sonnet 5.5는 Sonnet 5로 접히지 않는다", () => {
    expect(name("global.anthropic.claude-sonnet-5-5:1")).toBe("Claude Sonnet 5.5 (Global)");
    expect(name("anthropic:claude-sonnet-5-5:2")).toBe("Claude Sonnet 5.5");
    expect(name("us.anthropic.claude-sonnet-5:1")).toBe("Claude Sonnet 5");
  });
  test("Haiku 5.5(v2.33.0)는 Haiku 4.5와 구분되고, Sonnet 5.5 US도 5.5로 읽는다", () => {
    expect(name("global.anthropic.claude-haiku-5-5:1")).toBe("Claude Haiku 5.5 (Global)");
    expect(name("us.anthropic.claude-haiku-5-5:1")).toBe("Claude Haiku 5.5");
    expect(name("anthropic:claude-haiku-5-5:2")).toBe("Claude Haiku 5.5");
    expect(name("us.anthropic.claude-sonnet-5-5:1")).toBe("Claude Sonnet 5.5");
  });
  test("Fable 5.2(v2.41.0)는 Fable 5.1, Fable 5로 접히지 않는다", () => {
    expect(name("global.anthropic.claude-fable-5-2:1")).toBe("Claude Fable 5.2 (Global)");
    expect(name("us.anthropic.claude-fable-5-2:1")).toBe("Claude Fable 5.2");
    expect(name("anthropic:claude-fable-5-2:2")).toBe("Claude Fable 5.2");
    expect(name("global.anthropic.claude-fable-5-1:1")).toBe("Claude Fable 5.1 (Global)");
    expect(name("us.anthropic.claude-fable-5:1")).not.toContain("Fable");  // Fable 5 left monitoring in v2.42.0
  });
  test("GPT 6.1 Sol 3채널과 GPT 6 Sol은 서로 구분된다", () => {
    expect(name("openai:global:global.openai.gpt-6.1-sol:1")).toBe("GPT 6.1 Sol (Global)");
    expect(name("openai:us:us.openai.gpt-6.1-sol:1")).toBe("GPT 6.1 Sol (US)");
    expect(name("openai:us-east-1:openai.gpt-6.1-sol:1")).toBe("GPT 6.1 Sol (us-east-1)");
    expect(name("openai:us-east-1:openai.gpt-6-sol:1")).toBe("GPT 6 Sol (us-east-1)");
  });
  test("GPT 6.1 Terra 3채널(v2.38.0)은 GPT 6.1 Sol과 구분되고, Astra 인리전은 us-east-1이다", () => {
    expect(name("openai:global:global.openai.gpt-6.1-terra:1")).toBe("GPT 6.1 Terra (Global)");
    expect(name("openai:us:us.openai.gpt-6.1-terra:1")).toBe("GPT 6.1 Terra (US)");
    expect(name("openai:us-east-1:openai.gpt-6.1-terra:2")).toBe("GPT 6.1 Terra (us-east-1)");
    // GPT 5.6 Terra는 v2.43.0에 뺐다가 v2.45.0에 되살렸다(ADR-038, ADR-040) — 6.1 Terra로 접히지 않는다.
    expect(name("openai:us-east-1:openai.gpt-5.6-terra:1")).toBe("GPT 5.6 Terra (us-east-1)");
    expect(name("openai:us-east-1:openai.gpt-6-astra:1")).toBe("GPT 6 Astra (us-east-1)");
  });
  test("GPT 6.2 Astra, GPT 6.2 Sol 3채널씩(v2.44.0)은 GPT 6 Astra, GPT 6 Sol과 구분된다", () => {
    expect(name("openai:global:global.openai.gpt-6.2-astra:1")).toBe("GPT 6.2 Astra (Global)");
    expect(name("openai:us:us.openai.gpt-6.2-astra:1")).toBe("GPT 6.2 Astra (US)");
    expect(name("openai:us-east-1:openai.gpt-6.2-astra:2")).toBe("GPT 6.2 Astra (us-east-1)");
    expect(name("openai:global:global.openai.gpt-6.2-sol:1")).toBe("GPT 6.2 Sol (Global)");
    expect(name("openai:us:us.openai.gpt-6.2-sol:1")).toBe("GPT 6.2 Sol (US)");
    expect(name("openai:us-east-1:openai.gpt-6.2-sol:3")).toBe("GPT 6.2 Sol (us-east-1)");
    // 이웃 패밀리는 그대로다
    expect(name("openai:global:global.openai.gpt-6-astra:1")).toBe("GPT 6 Astra (Global)");
    expect(name("openai:us:us.openai.gpt-6-sol:1")).toBe("GPT 6 Sol (US)");
    expect(name("openai:us-east-1:openai.gpt-6.1-sol:1")).toBe("GPT 6.1 Sol (us-east-1)");
  });
  test("GPT 5.6 Sol, Terra, Luna(v2.45.0 복귀)는 Global과 us-east-1로 읽히고 GPT 6 세대와 구분된다", () => {
    expect(name("openai:global:global.openai.gpt-5.6-sol:1")).toBe("GPT 5.6 Sol (Global)");
    expect(name("openai:us-east-1:openai.gpt-5.6-sol:2")).toBe("GPT 5.6 Sol (us-east-1)");
    expect(name("openai:global:global.openai.gpt-5.6-terra:1")).toBe("GPT 5.6 Terra (Global)");
    expect(name("openai:global:global.openai.gpt-5.6-luna:1")).toBe("GPT 5.6 Luna (Global)");
    expect(name("openai:us-east-1:openai.gpt-5.6-luna:3")).toBe("GPT 5.6 Luna (us-east-1)");
    // 이웃 패밀리는 그대로다
    expect(name("openai:global:global.openai.gpt-6-sol:1")).toBe("GPT 6 Sol (Global)");
    expect(name("openai:us-east-1:openai.gpt-6-luna:1")).toBe("GPT 6 Luna (us-east-1)");
    // GPT 5.5는 v2.43.0에 뺀 그대로다 — family 이름 없이 "GPT"로만 읽힌다.
    expect(name("openai:us-east-1:openai.gpt-5.5:1")).toBe("GPT (us-east-1)");
  });
  test("FM id 안의 ':'는 마지막 iteration 세그먼트만 떼어 낸다", () => {
    expect(name("us.amazon.nova-2-lite-v1:0:1")).toBe("Nova 2.0 Lite");
    expect(name("bedrock:ap-northeast-2:anthropic.claude-sonnet-5:3")).toBe("Claude Sonnet 5 (ap-northeast-2)");
  });
});
