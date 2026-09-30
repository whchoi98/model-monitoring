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
  test("GPT 6.1 Sol 3채널과 GPT 6 Sol은 서로 구분된다", () => {
    expect(name("openai:global:global.openai.gpt-6.1-sol:1")).toBe("GPT 6.1 Sol (Global)");
    expect(name("openai:us:us.openai.gpt-6.1-sol:1")).toBe("GPT 6.1 Sol (US)");
    expect(name("openai:us-east-1:openai.gpt-6.1-sol:1")).toBe("GPT 6.1 Sol (us-east-1)");
    expect(name("openai:us-east-1:openai.gpt-6-sol:1")).toBe("GPT 6 Sol (us-east-1)");
  });
  test("FM id 안의 ':'는 마지막 iteration 세그먼트만 떼어 낸다", () => {
    expect(name("us.amazon.nova-2-lite-v1:0:1")).toBe("Nova 2.0 Lite");
    expect(name("global.anthropic.claude-haiku-4-5-20251001-v1:0:3")).toBe("Claude Haiku 4.5 (Global)");
  });
});
