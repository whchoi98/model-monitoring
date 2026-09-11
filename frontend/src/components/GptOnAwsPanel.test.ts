/** GPT on AWS 패널 라인 인코딩 순수 로직 (v2.25.1) — 색(리전) × 선 패턴(family) 회귀.
 *
 * model_name 문자열만으로 리전과 family를 되찾는 로직이라, pseudo-region "(US)"가 추가되면
 * "(us-west-2)"와 혼동되거나 GPT 6 Astra가 GPT 5.4로 접히기 쉽다. 그 두 가지를 고정한다.
 */
import { describe, expect, test } from "vitest";
import { familyOf, regionOf } from "./GptOnAwsPanel";

describe("regionOf", () => {
  test("US CRIS pseudo-region (v2.25.1)", () => {
    expect(regionOf("OpenAI GPT 6 Astra (US)")).toBe("US");
  });
  test("Mantle in-region은 US CRIS와 구분된다", () => {
    expect(regionOf("OpenAI GPT 6 Astra (us-west-2)")).toBe("us-west-2");
    expect(regionOf("OpenAI GPT 5.4 (us-east-1)")).toBe("us-east-1");
    expect(regionOf("OpenAI GPT 5.5 (us-east-2)")).toBe("us-east-2");
  });
  test("Global CRIS", () => {
    expect(regionOf("OpenAI GPT 5.6 Terra (Global)")).toBe("Global");
    expect(regionOf("OpenAI GPT 6 Astra (Global)")).toBe("Global");
  });
  test("리전 표기가 없으면 빈 문자열", () => {
    expect(regionOf("OpenAI GPT 5.4")).toBe("");
  });
});

describe("familyOf", () => {
  test("4개 family 모두 판별", () => {
    expect(familyOf("OpenAI GPT 6 Astra (Global)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 6 Astra (US)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 6 Astra (us-west-2)")).toBe("GPT 6 Astra");
    expect(familyOf("OpenAI GPT 5.6 Terra (us-east-1)")).toBe("GPT 5.6 Terra");
    expect(familyOf("OpenAI GPT 5.5 (us-east-2)")).toBe("GPT 5.5");
    expect(familyOf("OpenAI GPT 5.4 (us-west-2)")).toBe("GPT 5.4");
  });
});
