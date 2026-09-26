/** 비용 단가 화면 정적 렌더 (v2.30.0) — 응답 순서 그대로의 제공사 섹션, #ref-n 각주, In-Region 여러 줄 셀,
 * 빈 셀 "—", 다운로드 링크, 참고 사항 5개, 면책 문구 두 번, 줄바꿈 단위(break-keep, nowrap 토큰), 같은 고정 열 폭.
 * 브라우저 동작은 e2e/pricing.spec.ts가 맡는다.
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
/** Visible text of a markup fragment (tags dropped), for wording checks that must not depend on nowrap spans. */
const plain = (html: string) => html.replace(/<[^>]+>/g, "");

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
    expect(plain(inRegion)).toContain("$2.75 / $16.50 us-east-1, us-east-2[7]");
    expect(plain(inRegion)).toContain("$2.50 / $15.00 us-west-2[7]");
  });

  test("리전 id, 가격 쌍, 각주는 토큰 중간에서 줄이 바뀌지 않는다 (리전 목록은 항목 사이에서만)", () => {
    const html = render("ko");
    const inRegion = cell(html, "gpt-5.4", "in_region");
    // Each region is its own nowrap span; the footnote rides inside the last one.
    expect(inRegion).toMatch(/data-regions="true"[^>]*><span class="whitespace-nowrap">us-east-1<\/span>, <span class="whitespace-nowrap">us-east-2<sup/);
    expect(inRegion).toMatch(/<span class="whitespace-nowrap"><span class="tabular-nums text-gray-100"[^>]*>\$2\.75 \/ \$16\.50<\/span><\/span>/);
    // Without regions the footnote stays with the price pair.
    expect(cell(html, "claude-opus-5-5", "us")).toMatch(/<span class="whitespace-nowrap"><span class="tabular-nums text-gray-100"[^>]*>\$4\.40 \/ \$22\.00<\/span><sup/);
    // Dates and price pairs inside badge details, and the footnote after the last token.
    expect(cell(html, "claude-fable-5-1", "us")).toContain('<span class="whitespace-nowrap">2026-09-20</span>');
    expect(cell(html, "gpt-5.6-sol", "in_region")).toMatch(/<span class="whitespace-nowrap">\$5\.50 \/ \$33\.00<sup/);
    expect(cell(html, "gpt-5.6-sol", "in_region")).toMatch(/data-badge="promo"[^>]*break-keep[^>]*>프로모션\(최소 <span class="whitespace-nowrap">2026-11-21<\/span>/);
    expect(cell(html, "claude-fable-5-1", "us")).toMatch(/data-badge="unverified" class="[^"]*whitespace-nowrap/);
    expect(html).toMatch(/data-pending-count="true" class="whitespace-nowrap/);
    expect(html).toMatch(/whitespace-nowrap[^"]*"[^>]*>수동 메모</);
    expect(html).toContain('<span class="whitespace-nowrap">확인일 2026-09-26</span>');
  });

  test("한글 문장은 어절 단위로 줄바꿈하고, 긴 토큰만 어디서든 끊는다", () => {
    const html = render("ko");
    for (const marker of ['data-disclaimer="top"', 'data-disclaimer="bottom"']) {
      expect(html).toMatch(new RegExp(`${marker}[^>]*class="[^"]*break-keep \\[overflow-wrap:anywhere\\]`));
    }
    expect(html).toMatch(/<ol class="list-decimal[^"]*break-keep \[overflow-wrap:anywhere\]"/);
    expect(html).toMatch(/<ol class="space-y-0\.5[^"]*break-keep \[overflow-wrap:anywhere\]"/);
    expect(html).toMatch(/<h2 id="pricing-notes-title" class="[^"]*break-keep/);
    expect(html).toMatch(/data-badge-detail="pending" class="[^"]*break-keep/);
  });

  test("세 표는 같은 고정 열 폭, 표마다 이름(caption)이 있고 단위 범례는 표 위에 한 번", () => {
    const html = render("ko");
    const tables = html.match(/<table [^>]*>.*?<\/colgroup>/g) ?? [];
    expect(tables).toHaveLength(3);
    const layout = (table: string) => table.replace(/<caption[^>]*>.*?<\/caption>/, "");
    expect(new Set(tables.map(layout)).size).toBe(1);
    const first = tables[0] ?? "";
    expect(first).toContain("table-fixed");
    expect(first).toContain("min-w-[800px]");
    expect(count(first, "<col ")).toBe(5);
    expect(first).toContain('<col class="w-36"/>');
    expect(count(first, '<col class="w-[calc((100%_-_9rem)/4)]"/>')).toBe(4);
    expect(html).toContain('<caption class="sr-only">Anthropic Claude 단가 (입력 / 출력, 1M 토큰당 USD)</caption>');
    expect(render("en")).toContain('<caption class="sr-only">OpenAI prices (input / output, USD per 1M tokens)</caption>');
    expect(count(html, "data-unit-legend")).toBe(1);
    expect(html.indexOf("data-unit-legend")).toBeLessThan(html.indexOf("<table"));
    expect(plain(html.slice(html.indexOf("data-unit-legend"), html.indexOf("</p>", html.indexOf("data-unit-legend")))))
      .toContain("각 단가 셀: 입력 / 출력, 1M 토큰당 USD");
    expect(render("ko", null, { ...pricingFixture, families: [] })).not.toContain("data-unit-legend");
  });

  test("고정 모델 열은 불투명 배경과 오른쪽 구분선", () => {
    const html = render("ko");
    const sticky = html.match(/<th scope="row" class="([^"]*)"/)?.[1] ?? "";
    for (const name of ["sticky", "left-0", "bg-gray-900", "border-r", "border-r-gray-800"]) expect(sticky.split(" ")).toContain(name);
    expect(html).toMatch(/<th scope="col" class="sticky left-0 z-10 border-r border-r-gray-800 bg-gray-900/);
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
    expect(html).toContain("마지막 공식 단가 동기화: ");
    expect(render("en")).toContain("Last official price sync: ");
    expect(render("en", null, { ...pricingFixture, last_sync: null, pending_review: 0 })).toContain("No official price sync has run yet");
  });

  test("배지 설명은 title 툴팁이 아니라 배지 옆 글자, 프로모션은 수동 메모 참고 자료로 각주", () => {
    const html = render("ko");
    expect(html).not.toMatch(/data-badge="[a-z_]+"[^>]*title=/);
    expect(plain(cell(html, "gpt-5.4", "in_region"))).toContain("새 값 $3.00 / $18.00");
    expect(cell(html, "gpt-5.4", "in_region")).toMatch(/data-badge-detail="pending"[^>]*><span class="tabular-nums">새 값 <span class="whitespace-nowrap">\$3\.00 \/ \$18\.00<\/span><\/span>/);
    expect(plain(cell(html, "claude-fable-5-1", "us"))).toContain("공식 출처 확인 2026-09-20");
    expect(plain(cell(render("en"), "claude-fable-5-1", "us"))).toContain("Confirmed at source 2026-09-20");
    expect(cell(html, "nova-2-lite", "us")).toMatch(/data-badge-detail="unverified"[^>]*><span[^>]*>초기값<\/span>/);
    const promo = cell(html, "gpt-5.6-sol", "in_region");
    expect(plain(promo)).toContain("프로모션 이전 단가 $5.50 / $33.00");
    expect(promo).toMatch(/data-badge-detail="promo"[^>]*>.*href="#ref-10"/);
    expect(promo).not.toContain("CHANGELOG v2.28.1");
    expect(plain(cell(render("en"), "gpt-5.6-sol", "global"))).toContain("Price before the promotion $5.00 / $30.00");
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
