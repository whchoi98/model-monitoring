/**
 * 트렌드 차트 가독성 개선 (v2.7.1) — 기본 선택·URL 상태 헬퍼 테스트.
 *
 * 28개 라인 동시 표시는 판독 불가 → 첫 방문 기본값은 "패밀리별 대표 1개"(~10라인).
 * 선택 상태(models/hours/category)는 URL query로 공유·복원 가능해야 한다.
 */
import { describe, expect, test } from "vitest";
import {
  defaultTrendSelection,
  parseTrendQuery,
  buildTrendQuery,
} from "./trendSelection";

const MODELS = [
  "Anthropic Claude Fable 5 (US)",
  "Bedrock Claude Fable 5 (Global)",
  "Bedrock Claude Fable 5 (US)",
  "Bedrock Claude Opus 4.8 (Global)",
  "Bedrock Claude Opus 4.8 (US)",
  "Bedrock Nova 2.0 Lite (US)",
  "OpenAI GPT 5.5 (us-east-1)",
  "OpenAI GPT 5.5 (1P)",
];

describe("defaultTrendSelection", () => {
  test("패밀리별 대표 1개만 선택한다 (채널 우선순위 최상위)", () => {
    const sel = defaultTrendSelection(MODELS);
    // Fable 5: Anthropic이 채널 rank 0 → 대표
    expect(sel.has("Anthropic Claude Fable 5 (US)")).toBe(true);
    expect(sel.has("Bedrock Claude Fable 5 (Global)")).toBe(false);
    // Opus 4.8: Anthropic 채널 없음 → Global이 대표
    expect(sel.has("Bedrock Claude Opus 4.8 (Global)")).toBe(true);
    expect(sel.has("Bedrock Claude Opus 4.8 (US)")).toBe(false);
    // 패밀리 수만큼만: Fable 5, Opus 4.8, Nova, GPT 5.5 → 4개
    expect(sel.size).toBe(4);
  });

  test("빈 입력이면 빈 선택", () => {
    expect(defaultTrendSelection([]).size).toBe(0);
  });
});

describe("URL query 직렬화/복원", () => {
  test("라운드트립: models + hours + category", () => {
    const models = new Set(["Bedrock Claude Opus 4.8 (Global)", "OpenAI GPT 5.5 (1P)"]);
    const qs = buildTrendQuery(models, 24, "reasoning");
    const parsed = parseTrendQuery(qs);
    expect(parsed.models).toEqual(models);
    expect(parsed.hours).toBe(24);
    expect(parsed.category).toBe("reasoning");
  });

  test("빈 선택(전체 보기)은 models=all 로 표현되어 기본값과 구분된다", () => {
    const qs = buildTrendQuery(new Set(), 1, null);
    expect(qs).toContain("models=all");
    const parsed = parseTrendQuery(qs);
    expect(parsed.models).toEqual(new Set()); // 전체 보기
    expect(parsed.explicitAll).toBe(true);
  });

  test("models 파라미터가 없으면 undefined — 첫 방문(대표 기본값) 신호", () => {
    const parsed = parseTrendQuery("?hours=6");
    expect(parsed.models).toBeUndefined();
    expect(parsed.hours).toBe(6);
    expect(parsed.category).toBeNull();
  });

  test("소수 hours(0.5 등)와 특수문자 모델명을 안전하게 처리한다", () => {
    const models = new Set(["OpenAI GPT 5.5 (us-east-1)"]);
    const qs = buildTrendQuery(models, 0.5, null);
    const parsed = parseTrendQuery(qs);
    expect(parsed.hours).toBe(0.5);
    expect(parsed.models).toEqual(models);
  });
});
