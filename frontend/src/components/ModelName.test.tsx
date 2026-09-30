/** 모델 라벨의 끝 괄호 채널 표기를 nowrap 한 덩어리로 (v2.32.0) — 390px 카드 제목이 "(ap-" / "northeast-2)"로 끊기던 회귀.
 * 실제 줄바꿈은 e2e/channel-labels.spec.ts가 390px에서 확인한다.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import ModelName, { splitChannelSuffix } from "./ModelName";

describe("splitChannelSuffix", () => {
  test("splits off the parenthesised channel of every label shape", () => {
    expect(splitChannelSuffix("Bedrock Claude Opus 5 (ap-northeast-2)")).toEqual(["Bedrock Claude Opus 5", "(ap-northeast-2)"]);
    expect(splitChannelSuffix("OpenAI GPT 6.1 Sol (us-east-1)")).toEqual(["OpenAI GPT 6.1 Sol", "(us-east-1)"]);
    expect(splitChannelSuffix("Bedrock Claude Fable 5.1 (Global)")).toEqual(["Bedrock Claude Fable 5.1", "(Global)"]);
    expect(splitChannelSuffix("Anthropic Claude Sonnet 5.5 (US)")).toEqual(["Anthropic Claude Sonnet 5.5", "(US)"]);
  });

  test("leaves labels without a single-token suffix alone", () => {
    expect(splitChannelSuffix("OpenAI GPT 5.4")).toBeNull();
    expect(splitChannelSuffix("Custom model (two words)")).toBeNull();
    expect(splitChannelSuffix("(Global)")).toBeNull();
  });
});

describe("ModelName", () => {
  test("wraps the channel suffix in a nowrap span and keeps the visible text", () => {
    const html = renderToStaticMarkup(<ModelName name="Bedrock Claude Opus 5 (ap-northeast-2)" />);
    expect(html).toBe('Bedrock Claude Opus 5 <span class="whitespace-nowrap">(ap-northeast-2)</span>');
  });

  test("renders a label without a suffix as plain text", () => {
    expect(renderToStaticMarkup(<ModelName name="OpenAI GPT 5.4" />)).toBe("OpenAI GPT 5.4");
  });
});
