/**
 * Model Explorer (v2.9.0) — 모델 ID에서 호출 채널·네이티브 ID·링크를 유도하는
 * 순수 로직 테스트. 7개 provider path의 키 스킴(ADR-019/020/027/031)을 고정한다.
 * 코드 예제는 v2.40.0부터 백엔드가 만든다 — backend/tests/test_explorer_examples.py가 v2.39.0 출력과의 바이트 일치를 고정한다.
 */
import { describe, expect, test } from "vitest";
import { channelOf, nativeId, modelLinks } from "./modelExplorer";

describe("channelOf — 7개 provider path 판별", () => {
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
  test("OpenAI Bedrock Global CRIS (v2.20.0)", () => {
    const ch = channelOf("openai:global:global.openai.gpt-5.6-sol");
    expect(ch.type).toBe("openai-mantle");
    // global 프로파일은 bedrock-mantle 호스트 미지원 — Seoul bedrock-runtime OpenAI-compat만 가능.
    expect(ch.endpoint).toBe("https://bedrock-runtime.ap-northeast-2.amazonaws.com/openai/v1");
    expect(ch.label).toContain("Global");
  });
  test("OpenAI Bedrock US CRIS (v2.25.0)", () => {
    const ch = channelOf("openai:us:us.openai.gpt-6-astra");
    expect(ch.type).toBe("openai-mantle");
    // us. 프로파일도 bedrock-mantle 호스트 미지원 — us-east-1 bedrock-runtime OpenAI-compat만 가능.
    expect(ch.endpoint).toBe("https://bedrock-runtime.us-east-1.amazonaws.com/openai/v1");
    expect(ch.endpoint).not.toContain("bedrock-mantle"); // 존재하지 않는 호스트 회귀 방지
    expect(ch.region).toBe("US");
    expect(ch.label).toContain("US");
  });
  test("GPT 6 Astra 인리전(us-west-2)은 기존 Mantle 호스트", () => {
    const ch = channelOf("openai:us-west-2:openai.gpt-6-astra");
    expect(ch.type).toBe("openai-mantle");
    expect(ch.endpoint).toBe("https://bedrock-mantle.us-west-2.api.aws/openai/v1");
    expect(ch.region).toBe("us-west-2");
  });
  test("Bedrock In-Region 온디맨드(v2.32.0) — bedrock:<region>:<fm id>", () => {
    const ch = channelOf("bedrock:ap-northeast-2:anthropic.claude-opus-5");
    // type은 bedrock 유지 — 필터와 배지 색이 기존 Bedrock 카드와 같게 적용된다.
    expect(ch.type).toBe("bedrock");
    expect(ch.region).toBe("ap-northeast-2");
    expect(ch.badge).toBe("In-Region");
    expect(ch.endpoint).toBe("https://bedrock-runtime.ap-northeast-2.amazonaws.com");
    expect(ch.label).toContain("In-Region");
  });
  test("카드 배지 — 기존 6종 회귀 (ModelExplorer 카드의 예전 삼항식과 같은 값)", () => {
    expect(channelOf("global.anthropic.claude-fable-5").badge).toBe("Global");
    expect(channelOf("us.anthropic.claude-haiku-4-5-20251001-v1:0").badge).toBe("US");
    expect(channelOf("anthropic:claude-sonnet-5").badge).toBe("CP");
    expect(channelOf("openai:1p:gpt-5.5").badge).toBe("1P");
    expect(channelOf("openai:global:global.openai.gpt-6.1-sol").badge).toBe("Global");
    expect(channelOf("openai:us:us.openai.gpt-6.1-sol").badge).toBe("US");
    expect(channelOf("openai:us-east-1:openai.gpt-6.1-sol").badge).toBe("us-east-1");
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
  test("OpenAI Global CRIS는 global. 접두사 포함 프로파일 id", () => {
    expect(nativeId("openai:global:global.openai.gpt-5.6-terra")).toBe("global.openai.gpt-5.6-terra");
  });
  test("OpenAI US CRIS는 us. 접두사 포함 프로파일 id", () => {
    expect(nativeId("openai:us:us.openai.gpt-6-astra")).toBe("us.openai.gpt-6-astra");
    expect(nativeId("openai:us-west-2:openai.gpt-6-astra")).toBe("openai.gpt-6-astra");
  });
  test("Bedrock In-Region은 기본 모델 ID (접두 제거, FM id의 :는 보존)", () => {
    expect(nativeId("bedrock:ap-northeast-2:anthropic.claude-sonnet-5")).toBe("anthropic.claude-sonnet-5");
    expect(nativeId("bedrock:ap-northeast-2:anthropic.claude-haiku-4-5-20251001-v1:0")).toBe("anthropic.claude-haiku-4-5-20251001-v1:0");
  });
});

describe("modelLinks — 문서·대시보드 링크", () => {
  test("Bedrock 모델은 AWS 문서·콘솔 링크 포함", () => {
    const links = modelLinks("global.anthropic.claude-fable-5", "Bedrock Claude Fable 5 (Global)");
    const urls = links.map((l) => l.url).join(" ");
    expect(urls).toContain("docs.aws.amazon.com/bedrock");
    expect(urls).toContain("console.aws.amazon.com");
    expect(urls).toContain("region=ap-northeast-2");
  });
  test("Bedrock US 프로파일의 콘솔 링크는 us-east-1", () => {
    const urls = modelLinks("us.anthropic.claude-haiku-5-5", "Bedrock Claude Haiku 5.5 (US)").map((l) => l.url).join(" ");
    expect(urls).toContain("region=us-east-1");
    expect(urls).not.toContain("region=ap-northeast-2");
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
  test("Bedrock In-Region은 그 리전 콘솔 링크 + Anthropic 문서", () => {
    const urls = modelLinks("bedrock:ap-northeast-2:anthropic.claude-opus-5", "Bedrock Claude Opus 5 (ap-northeast-2)").map((l) => l.url).join(" ");
    expect(urls).toContain("region=ap-northeast-2");
    expect(urls).toContain("docs.claude.com");
  });
  test("Anthropic CP는 Anthropic 문서 링크", () => {
    const urls = modelLinks("anthropic:claude-sonnet-5", "Anthropic Claude Sonnet 5 (US)").map((l) => l.url).join(" ");
    expect(urls).toContain("docs.claude.com");
  });
});

describe("i18n — lang 파라미터 (v2.16.2)", () => {
  test("EN 선택 시 링크 라벨이 영어로 출력된다", () => {
    const links = modelLinks("global.anthropic.claude-fable-5", "Bedrock Claude Fable 5 (Global)", "en");
    expect(links[0].label).toContain("trend");
    expect(links.some((l) => l.label.includes("documentation") || l.label.includes("docs") || l.label.includes("Docs"))).toBe(true);
  });
  test("기본값(ko)은 기존 한국어 출력 유지", () => {
    expect(modelLinks("anthropic:claude-fable-5", "Anthropic Claude Fable 5 (US)")[0].label).toBe("📈 이 모델 트렌드 보기");
  });
});
