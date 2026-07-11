/**
 * Model Explorer (v2.9.0) — 모델 ID에서 호출 채널·네이티브 ID·코드 예제·링크를 유도하는
 * 순수 로직 테스트. 5개 provider path의 키 스킴(ADR-019/020)을 고정한다.
 */
import { describe, expect, test } from "vitest";
import { channelOf, nativeId, codeExamples, modelLinks } from "./modelExplorer";

describe("channelOf — 5개 provider path 판별", () => {
  test("Bedrock Global 프로파일", () => {
    const ch = channelOf("global.anthropic.claude-fable-5");
    expect(ch.type).toBe("bedrock");
    expect(ch.label).toContain("Global");
  });
  test("Bedrock US 프로파일", () => {
    expect(channelOf("us.anthropic.claude-haiku-4-5-20251001-v1:0").type).toBe("bedrock");
    expect(channelOf("us.amazon.nova-2-lite-v1:0").label).toContain("US");
  });
  test("Anthropic CP on AWS", () => {
    const ch = channelOf("anthropic:claude-sonnet-5");
    expect(ch.type).toBe("anthropic-cp");
    expect(ch.endpoint).toContain("aws-external-anthropic");
  });
  test("OpenAI Mantle (리전별)", () => {
    const ch = channelOf("openai:us-west-2:openai.gpt-5.4");
    expect(ch.type).toBe("openai-mantle");
    expect(ch.endpoint).toBe("https://bedrock-mantle.us-west-2.api.aws/openai/v1");
  });
  test("OpenAI 1P direct", () => {
    const ch = channelOf("openai:1p:gpt-5.5");
    expect(ch.type).toBe("openai-1p");
    expect(ch.endpoint).toBe("https://api.openai.com/v1");
  });
});

describe("nativeId — 실제 호출에 쓰는 모델 ID", () => {
  test("Bedrock은 프로파일 ID 그대로", () => {
    expect(nativeId("global.anthropic.claude-fable-5")).toBe("global.anthropic.claude-fable-5");
  });
  test("Anthropic CP는 prefix 제거", () => {
    expect(nativeId("anthropic:claude-sonnet-5")).toBe("claude-sonnet-5");
  });
  test("OpenAI Mantle은 openai.<id>", () => {
    expect(nativeId("openai:us-east-1:openai.gpt-5.5")).toBe("openai.gpt-5.5");
  });
  test("OpenAI 1P는 native id", () => {
    expect(nativeId("openai:1p:gpt-5.4")).toBe("gpt-5.4");
  });
});

describe("codeExamples — 채널에 맞는 SDK 예제 + API 종류 표기", () => {
  test("Bedrock(Claude) → Converse API + InvokeModel API 두 탭, 각각 설명 포함", () => {
    const ex = codeExamples("us.anthropic.claude-haiku-4-5-20251001-v1:0");
    expect(ex.map((e) => e.api)).toEqual(["Converse API", "InvokeModel API"]);
    expect(ex[0].code).toContain("converse_stream");
    expect(ex[0].code).toContain("us.anthropic.claude-haiku-4-5-20251001-v1:0");
    expect(ex[0].description.length).toBeGreaterThan(10); // API 의미 설명
    expect(ex[1].code).toContain("invoke_model");
    expect(ex[1].description).toContain("네이티브");
  });
  test("Bedrock(Nova) → Converse API 단일 탭", () => {
    const ex = codeExamples("us.amazon.nova-2-lite-v1:0");
    expect(ex.map((e) => e.api)).toEqual(["Converse API"]);
  });
  test("Anthropic CP → Messages API 표기 + 설명", () => {
    const ex = codeExamples("anthropic:claude-fable-5");
    expect(ex[0].api).toBe("Messages API");
    expect(ex[0].description).toContain("Anthropic");
    expect(ex[0].code).toContain("aws-external-anthropic");
    expect(ex[0].code).toContain("anthropic-workspace");
    expect(ex[0].code).toContain('"claude-fable-5"');
  });
  test("OpenAI Mantle → Responses API 표기", () => {
    const ex = codeExamples("openai:us-east-2:openai.gpt-5.5");
    expect(ex[0].api).toBe("Responses API");
    expect(ex[0].description.length).toBeGreaterThan(10);
    expect(ex[0].code).toContain("bedrock-mantle.us-east-2");
    expect(ex[0].code).toContain("ABSK");
  });
  test("OpenAI 1P → Responses API 표기", () => {
    const ex = codeExamples("openai:1p:gpt-5.5");
    expect(ex[0].api).toBe("Responses API");
    expect(ex[0].code).toContain("responses");
    expect(ex[0].code).toContain('"gpt-5.5"');
  });
});

describe("modelLinks — 문서·대시보드 링크", () => {
  test("Bedrock 모델은 AWS 문서·콘솔 링크 포함", () => {
    const links = modelLinks("global.anthropic.claude-fable-5", "Bedrock Claude Fable 5 (Global)");
    const urls = links.map((l) => l.url).join(" ");
    expect(urls).toContain("docs.aws.amazon.com/bedrock");
    expect(urls).toContain("console.aws.amazon.com");
  });
  test("모든 모델에 대시보드 트렌드 바로가기 (URL 공유 형식)", () => {
    const links = modelLinks("openai:1p:gpt-5.4", "OpenAI GPT 5.4 (1P)");
    const trend = links.find((l) => l.url.startsWith("/?models="));
    expect(trend).toBeDefined();
    expect(trend!.url).toContain(encodeURIComponent("OpenAI GPT 5.4 (1P)"));
    expect(trend!.url).toContain("hours=24");
  });
  test("OpenAI 1P는 OpenAI 문서 링크", () => {
    const urls = modelLinks("openai:1p:gpt-5.5", "OpenAI GPT 5.5 (1P)").map((l) => l.url).join(" ");
    expect(urls).toContain("platform.openai.com");
  });
  test("Anthropic CP는 Anthropic 문서 링크", () => {
    const urls = modelLinks("anthropic:claude-sonnet-5", "Anthropic Claude Sonnet 5 (US)").map((l) => l.url).join(" ");
    expect(urls).toContain("docs.claude.com");
  });
});
