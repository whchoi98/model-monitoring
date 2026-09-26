/** 비용 단가 화면 정적 렌더 (v2.30.0) — 응답 순서 그대로의 제공사 섹션, #ref-n 각주, In-Region 여러 줄 셀,
 * 빈 셀 "—", 다운로드 링크, 참고 사항 5개, 면책 문구 두 번. 브라우저 동작은 e2e/pricing.spec.ts가 맡는다.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, test } from "vitest";
import type { PricingResponse } from "@/lib/types";
import { pricingFixture } from "../../e2e/fixtures";
import { PricingContent, providerSections, tableScrollCue } from "./PricingPanel";

function render(lang: "ko" | "en", highlight: number | null = null, data: PricingResponse = pricingFixture): string {
  return renderToStaticMarkup(
    <PricingContent data={data} lang={lang} today={new Date("2026-09-26T12:00:00Z")} highlight={highlight} onFootnote={() => {}} />,
  );
}

const count = (html: string, needle: string) => html.split(needle).length - 1;

/** Markup of one tier cell in a family row, up to its closing </td>. */
function cell(html: string, family: string, tier: string): string {
  const row = html.slice(html.indexOf(`data-family="${family}"`));
  const start = row.indexOf(`data-tier="${tier}"`);
  return row.slice(start, row.indexOf("</td>", start));
}

describe("providerSections", () => {
  test("응답 순서 그대로 연속한 제공사끼리 묶는다 (다시 정렬하지 않는다)", () => {
    expect(providerSections(pricingFixture.families).map((s) => [s.provider, s.families.length]))
      .toEqual([["anthropic", 2], ["amazon", 1], ["openai", 3]]);
    const [fable, , nova, astra] = pricingFixture.families;
    expect(providerSections([astra, fable, nova, astra]).map((s) => s.provider)).toEqual(["openai", "anthropic", "amazon", "openai"]);
  });
});

describe("tableScrollCue", () => {
  test("넘치지 않으면 단서가 없다 (1px 오차는 무시)", () => {
    expect(tableScrollCue(0, 1182, 1182)).toEqual({ overflow: false, scrolled: false, moreRight: false });
    expect(tableScrollCue(0, 324, 325)).toEqual({ overflow: false, scrolled: false, moreRight: false });
  });

  test("폰 폭: 처음엔 오른쪽에 더 있고, 스크롤하면 scrolled, 끝에 닿으면 moreRight가 꺼진다", () => {
    expect(tableScrollCue(0, 324, 760)).toEqual({ overflow: true, scrolled: false, moreRight: true });
    expect(tableScrollCue(120, 324, 760)).toEqual({ overflow: true, scrolled: true, moreRight: true });
    expect(tableScrollCue(436, 324, 760)).toEqual({ overflow: true, scrolled: true, moreRight: false });
    expect(tableScrollCue(435.5, 324, 760).moreRight).toBe(false);
  });
});

describe("PricingContent", () => {
  test("제공사 섹션 순서, 고정 열, 소수 둘째 자리 셀, 빈 셀", () => {
    const html = render("ko");
    expect(html.indexOf(">Anthropic Claude</h2>")).toBeLessThan(html.indexOf(">Amazon Nova</h2>"));
    expect(html.indexOf(">Amazon Nova</h2>")).toBeLessThan(html.indexOf(">OpenAI</h2>"));
    expect(count(html, ">Claude Platform on AWS</th>")).toBe(3);
    expect(cell(html, "claude-opus-5-5", "us")).toContain("$4.40 / $22.00");
    expect(cell(html, "nova-2-lite", "cp")).toContain("—");
    expect(cell(html, "nova-2-lite", "cp")).toContain("단가 없음");
  });

  test("In-Region 원소마다 한 줄 (가격, 리전)", () => {
    const inRegion = cell(render("ko"), "gpt-5.4", "in_region");
    expect(count(inRegion, "data-price-line")).toBe(2);
    expect(inRegion).toMatch(/\$2\.75 \/ \$16\.50<\/span> <span[^>]*>us-east-1, us-east-2<\/span>/);
    expect(inRegion).toMatch(/\$2\.50 \/ \$15\.00<\/span> <span[^>]*>us-west-2<\/span>/);
  });

  test("각주는 #ref-n 링크, 참고 자료가 같은 id, 강조는 하나", () => {
    const html = render("ko", 7);
    expect(html).toContain('href="#ref-7"');
    expect(html).toContain('aria-label="참고 자료 7"');
    for (const ref of pricingFixture.references) expect(html).toContain(`id="ref-${ref.n}"`);
    expect(count(html, 'data-highlighted="true"')).toBe(1);
    expect(html).toMatch(/id="ref-7"[^>]*data-highlighted="true"/);
    expect(html).toMatch(/id="ref-10"[^>]*data-kind="manual_note"[^>]*>.*?수동 메모/);
  });

  test("다운로드 링크는 현재 언어의 export download 링크", () => {
    for (const format of ["csv", "md", "json"]) {
      expect(render("ko")).toContain(`href="/api/pricing/export?format=${format}&amp;lang=ko" download=""`);
    }
    expect(render("en")).toContain('href="/api/pricing/export?format=csv&amp;lang=en" download=""');
  });

  test("면책 문구 두 번, 참고 사항 5개, 동기화 상태와 검토 대기 수", () => {
    const html = render("ko");
    expect(count(html, pricingFixture.disclaimer.ko)).toBe(2);
    expect(count(render("en"), pricingFixture.disclaimer.en)).toBe(2);
    expect(count(html.slice(html.indexOf("pricing-notes-title")), "<li>")).toBeGreaterThanOrEqual(5);
    expect(html).toContain("<li>OpenAI는 입력 272K 이하 기준이다</li>");
    expect(html).toContain("완료");
    expect(html).toContain("검토 대기 1건");
    expect(render("en", null, { ...pricingFixture, last_sync: null, pending_review: 0 })).toContain("No automatic check has run yet");
  });

  test("배지 설명은 title 툴팁이 아니라 배지 옆 글자, 프로모션은 수동 메모 참고 자료로 각주", () => {
    const html = render("ko");
    expect(html).not.toMatch(/data-badge="[a-z_]+"[^>]*title=/);
    expect(cell(html, "gpt-5.4", "in_region")).toMatch(/data-badge-detail="pending"[^>]*><span[^>]*>새 값 \$3\.00 \/ \$18\.00<\/span>/);
    expect(cell(html, "claude-fable-5-1", "us")).toContain("마지막 확인 2026-09-20");
    expect(cell(html, "nova-2-lite", "us")).toMatch(/data-badge-detail="unverified"[^>]*><span[^>]*>초기값<\/span>/);
    const promo = cell(html, "gpt-5.6-sol", "in_region");
    expect(promo).toContain("프로모션 이전 단가 $5.50 / $33.00");
    expect(promo).toMatch(/data-badge-detail="promo"[^>]*>.*href="#ref-10"/);
    expect(promo).not.toContain("CHANGELOG v2.28.1");
    expect(cell(render("en"), "gpt-5.6-sol", "global")).toContain("Price before the promotion $5.00 / $30.00");
  });

  test("모델 ID 토글은 꺼진 상태로 시작하고 모델 ID 목록은 숨긴다, 스크롤 단서는 측정 전이라 없다", () => {
    const html = render("ko");
    expect(html).toMatch(/<button type="button" aria-pressed="false" data-model-ids-toggle="true"[^>]*>모델 ID 보기<\/button>/);
    expect(render("en")).toContain(">Show model IDs</button>");
    expect(html).not.toContain("data-model-ids=");
    expect(html).not.toContain("data-scroll-hint");
    expect(html).not.toContain("data-scroll-fade");
    expect(count(html, "data-pricing-scroll")).toBe(3);
  });

  test("면책 상자의 Anthropic 요금 링크, 참고 자료 확인일, 검토 대기 0건이면 숨김", () => {
    const html = render("ko");
    expect(html).toContain('href="https://platform.claude.com/docs/en/about-claude/pricing"');
    expect(html).toContain("확인일 2026-09-26");
    const none = render("en", null, { ...pricingFixture, pending_review: 0 });
    expect(none).not.toContain("data-pending-count");
    expect(none).not.toContain("pending review");
  });
});
