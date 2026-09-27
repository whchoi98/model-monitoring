/** 비용 단가 화면 정적 렌더 (v2.30.0, v2.31.0) — 응답 순서 그대로의 제공사 섹션(Anthropic Claude, OpenAI, Amazon Nova),
 * 제공사별 열 머리글(AWS Bedrock - Global CRIS 등), Nova의 빈 첫 열, 모르는 제공사의 기본 열, 캐시 줄과 GPT 긴 컨텍스트 줄, #ref-n 각주,
 * In Region 여러 줄 셀, 빈 셀 "—", 다운로드 링크, 참고 사항 9개, 모든 참고 자료가 각주로 인용됨, 면책 문구 두 번, 줄바꿈 단위(break-keep, nowrap 토큰),
 * 같은 고정 열 폭. 브라우저 동작은 e2e/pricing.spec.ts가 맡는다.
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
/** Visible text of a markup fragment (tags dropped, entities decoded), for wording checks that must not depend on nowrap spans. */
const plain = (html: string) => html.replace(/<[^>]+>/g, "").replace(/&#x27;/g, "'").replace(/&quot;/g, '"').replace(/&amp;/g, "&");

/** Markup of one tier cell in a family row, up to its closing </td>. */
function cell(html: string, family: string, tier: string): string {
  const row = html.slice(html.indexOf(`data-family="${family}"`));
  const start = row.indexOf(`data-tier="${tier}"`);
  return row.slice(start, row.indexOf("</td>", start));
}

/** Markup of one provider section, up to its closing </section>. */
function section(html: string, provider: string): string {
  const start = html.indexOf(`aria-labelledby="pricing-${provider}"`);
  return html.slice(start, html.indexOf("</section>", start));
}

/** Visible texts of a provider table's column headers (the blank Nova column is a td, not a header). */
function headers(html: string, provider: string): string[] {
  const head = section(html, provider);
  const thead = head.slice(head.indexOf("<thead>"), head.indexOf("</thead>"));
  return [...thead.matchAll(/<th scope="col"[^>]*>(.*?)<\/th>/g)].map((match) => plain(match[1]));
}

/** Visible text of the first cache (`cache`) or long-context (`long`) line in a markup fragment, or null. */
function line(html: string, kind: "cache" | "long"): string | null {
  const match = new RegExp(`data-${kind}-line="true"[^>]*>(.*?)</span></span>`).exec(html);
  return match ? plain(match[1]) : null;
}

const NOTES_KO = [
  "단가는 USD, 1M 토큰당, Standard 등급 기준이다",
  "AWS Bedrock - Global CRIS 단가는 같은 모델의 US CRIS, In Region 단가와 다를 수 있다",
  "GPT의 AWS Bedrock - US CRIS와 In Region 단가는 같다. AWS가 두 채널 모두 OpenAI 공식 가격에 10%를 더하고, Global CRIS는 OpenAI 공식 가격과 같다",
  "캐시 쓰기는 Claude의 5분 캐시, OpenAI 공식 문서의 cache writes, Nova의 캐시 쓰기 단가이고, 1시간 쓰기는 Claude의 1시간 캐시 단가다",
  "GPT의 긴 컨텍스트 요금은 OpenAI가 정한 짧은 컨텍스트 한도(GPT 5.4, 5.5는 272K)를 넘는 요청에 적용된다",
  "OpenAI 공식 가격은 OpenAI 직접 API 단가이며 비용 계산에 쓰지 않는다",
  "캐시와 긴 컨텍스트 단가는 표시만 하며, 비용 화면은 입력과 출력 단가로 계산한다",
  "batch, flex, priority(fast) 단가는 포함하지 않는다",
  "비용 화면은 각 프로브 시각의 단가로 계산한다",
];
const NOTES_EN = [
  "Prices are in USD per 1M tokens, Standard tier",
  "AWS Bedrock - Global CRIS prices can differ from the same model's US CRIS and In Region prices",
  "GPT prices on AWS Bedrock - US CRIS and In Region are the same: AWS adds 10% to the OpenAI official price on both, and Global CRIS equals the OpenAI official price",
  "Cache write is the Claude 5-minute cache price, OpenAI's cache writes price and the Nova cache write price, and 1h write is the Claude 1-hour cache price",
  "GPT long-context prices apply to requests above OpenAI's short-context limit (272K for GPT 5.4 and 5.5)",
  "The OpenAI official price is OpenAI's direct API price and is not used for cost calculations",
  "Cache and long-context prices are shown for reference, and the cost pages use input and output prices",
  "Batch, flex and priority (fast) prices are not included",
  "The cost pages use the price in effect at each probe's time",
];

describe("providerSections", () => {
  test("응답 순서 그대로 연속한 제공사끼리 묶는다 (다시 정렬하지 않는다)", () => {
    expect(providerSections(pricingFixture.families).map((s) => [s.provider, s.families.length]))
      .toEqual([["anthropic", 2], ["openai", 3], ["amazon", 1]]);
    const [fable, , astra, , , nova] = pricingFixture.families;
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
  test("제공사 섹션 순서 Anthropic Claude → OpenAI → Amazon Nova, 소수 둘째 자리 셀, 빈 셀", () => {
    const html = render("ko");
    expect(html.indexOf(">Anthropic Claude</h2>")).toBeLessThan(html.indexOf(">OpenAI</h2>"));
    expect(html.indexOf(">OpenAI</h2>")).toBeLessThan(html.indexOf(">Amazon Nova</h2>"));
    expect(cell(html, "claude-opus-5-5", "us")).toContain("$4.40 / $22.00");
    expect(cell(html, "gpt-6-astra", "openai_list")).toContain("$10.00 / $50.00");
    expect(plain(cell(html, "gpt-6-astra", "openai_list"))).toContain("$10.00 / $50.00[4]");
    expect(cell(html, "gpt-5.6-sol", "us")).toContain("—");
    expect(cell(html, "gpt-5.6-sol", "us")).toContain("단가 없음");
    expect(cell(html, "claude-opus-5-5", "in_region")).toContain("단가 없음");
  });

  test("표마다 제공사별 열 머리글, 두 조각 이름은 'AWS Bedrock -' 뒤에서만, 한 조각 이름은 단어 사이에서 줄이 바뀐다", () => {
    const bedrock = ["AWS Bedrock - Global CRIS", "AWS Bedrock - US CRIS", "AWS Bedrock - In Region"];
    const ko = render("ko");
    expect(headers(ko, "anthropic")).toEqual(["모델", "Claude Platform on AWS", ...bedrock]);
    expect(headers(ko, "openai")).toEqual(["모델", "OpenAI 공식 가격", ...bedrock]);
    expect(headers(ko, "amazon")).toEqual(["모델", ...bedrock]);
    const en = render("en");
    expect(headers(en, "anthropic")).toEqual(["Model", "Claude Platform on AWS", ...bedrock]);
    expect(headers(en, "openai")).toEqual(["Model", "OpenAI official price", ...bedrock]);
    expect(headers(en, "amazon")).toEqual(["Model", ...bedrock]);
    // Each part of a two-part title never breaks inside; a space separates them.
    expect(count(ko, '<span class="whitespace-nowrap">AWS Bedrock -</span> <span class="whitespace-nowrap">Global CRIS</span></th>')).toBe(3);
    expect(count(ko, '<span class="whitespace-nowrap">AWS Bedrock -</span> <span class="whitespace-nowrap">In Region</span></th>')).toBe(3);
    // A title without " - " is plain text, as in v2.30.0, so it wraps between words when a larger text size needs it.
    for (const [html, title] of [[ko, "Claude Platform on AWS"], [ko, "OpenAI 공식 가격"], [en, "Claude Platform on AWS"], [en, "OpenAI official price"]]) {
      expect(count(html, `font-medium">${title}</th>`)).toBe(1);
      expect(html).not.toContain(`<span class="whitespace-nowrap">${title}</span>`);
    }
    // Each provider shows only its own first column.
    expect(section(ko, "anthropic")).not.toContain('data-tier="openai_list"');
    expect(section(ko, "openai")).not.toContain('data-tier="cp"');
    expect(section(ko, "amazon")).not.toMatch(/data-tier="(cp|openai_list)"/);
  });

  test("Amazon Nova의 첫 열은 머리글과 칸 모두 비어 있다 (글자도 —도 없다)", () => {
    const html = render("ko");
    const nova = section(html, "amazon");
    const rows = count(nova, "data-family=");
    expect(rows).toBe(1);
    const blanks = [...html.matchAll(/<td aria-hidden="true" data-tier="none"[^>]*>(.*?)<\/td>/g)];
    expect(blanks).toHaveLength(rows + 1);
    expect(blanks.map((match) => match[1])).toEqual(["", ""]);
    expect(count(nova, 'data-tier="none"')).toBe(rows + 1);
    expect(count(section(html, "anthropic"), 'data-tier="none"')).toBe(0);
    expect(count(section(html, "openai"), 'data-tier="none"')).toBe(0);
    // The blank cell is the first cell after the model name, in the header and in the body.
    expect(nova).toMatch(/모델<\/th><td aria-hidden="true" data-tier="none"/);
    expect(nova).toMatch(/<\/th><td aria-hidden="true" data-tier="none" class="[^"]*"><\/td><td data-tier="global"/);
  });

  test("모르는 제공사(새 백엔드)는 멈추지 않고 기본 열(빈 첫 열 + AWS Bedrock 세 열), 섹션 이름은 제공사 문자열", () => {
    const nova = pricingFixture.families[pricingFixture.families.length - 1];
    const unknown = { ...nova, family_key: "gemini-9", family: "Gemini 9", provider: "google" as never };
    const data = { ...pricingFixture, families: [...pricingFixture.families, unknown] };
    const bedrock = ["AWS Bedrock - Global CRIS", "AWS Bedrock - US CRIS", "AWS Bedrock - In Region"];
    const ko = render("ko", null, data);
    expect(ko).toContain('<h2 id="pricing-google" class="mb-3 break-keep text-sm font-semibold text-gray-200">google</h2>');
    expect(ko).toContain('<caption class="sr-only">google 단가 (입력 / 출력, 1M 토큰당 USD)</caption>');
    expect(ko).toContain('aria-label="google 단가 표"');
    expect(headers(ko, "google")).toEqual(["모델", ...bedrock]);
    const google = section(ko, "google");
    expect(count(google, 'data-tier="none"')).toBe(2);
    expect(google).not.toMatch(/data-tier="(cp|openai_list)"/);
    expect(cell(ko, "gemini-9", "us")).toContain("$0.33 / $2.75");
    // The known sections are unchanged.
    expect(headers(ko, "amazon")).toEqual(["모델", ...bedrock]);
    expect(count(ko, "data-pricing-scroll")).toBe(4);
    expect(headers(render("en", null, data), "google")).toEqual(["Model", ...bedrock]);
  });

  test("In Region 원소마다 한 줄 (가격, 리전)", () => {
    const inRegion = cell(render("ko"), "gpt-5.4", "in_region");
    expect(count(inRegion, "data-price-line")).toBe(2);
    expect(plain(inRegion)).toContain("$2.75 / $16.50 us-east-1, us-east-2[7]");
    expect(plain(inRegion)).toContain("$2.50 / $15.00 us-west-2[7]");
  });

  test("둘째 줄은 프롬프트 캐싱, GPT 셋째 줄은 긴 컨텍스트", () => {
    const ko = render("ko");
    expect(line(cell(ko, "claude-opus-5-5", "global"), "cache")).toBe("캐시 읽기 $0.20, 쓰기 $5.00, 1시간 쓰기 $8.00");
    expect(line(cell(ko, "claude-opus-5-5", "us"), "cache")).toBe("캐시 읽기 $0.22, 쓰기 $5.50, 1시간 쓰기 $8.80");
    expect(line(cell(ko, "claude-fable-5-1", "cp"), "cache")).toBe("캐시 읽기 $0.25, 쓰기 $12.50, 1시간 쓰기 $20.00");
    expect(cell(ko, "claude-opus-5-5", "global")).toContain(
      'data-cache-line="true" class="mt-0.5 block text-[11px] leading-snug text-gray-400"><span class="whitespace-nowrap">캐시 읽기 $0.20</span>, '
      + '<span class="whitespace-nowrap">쓰기 $5.00</span>, <span class="whitespace-nowrap">1시간 쓰기 $8.00</span></span>',
    );
    expect(section(ko, "anthropic")).not.toContain("data-long-line");

    expect(line(cell(ko, "gpt-6-astra", "openai_list"), "cache")).toBe("캐시 읽기 $1.00, 쓰기 $12.50");
    expect(line(cell(ko, "gpt-6-astra", "openai_list"), "long")).toBe("긴 컨텍스트 $20.00 / $75.00, 캐시 읽기 $2.00, 쓰기 $25.00");
    expect(line(cell(ko, "gpt-6-astra", "us"), "long")).toBe("긴 컨텍스트 $22.00 / $82.50, 캐시 읽기 $2.20, 쓰기 $27.50");
    // The long-context pair may wrap between its label and its value; every other item stays whole.
    expect(cell(ko, "gpt-6-astra", "global")).toContain(
      'data-long-line="true" class="mt-0.5 block text-[11px] leading-snug text-gray-400"><span class="whitespace-nowrap">긴 컨텍스트</span> '
      + '<span class="whitespace-nowrap">$20.00 / $75.00</span>, <span class="whitespace-nowrap">캐시 읽기 $2.00</span>, '
      + '<span class="whitespace-nowrap">쓰기 $25.00</span></span>',
    );
    // GPT 5.4 has no cache write in either context.
    expect(line(cell(ko, "gpt-5.4", "openai_list"), "cache")).toBe("캐시 읽기 $0.25");
    expect(line(cell(ko, "gpt-5.4", "openai_list"), "long")).toBe("긴 컨텍스트 $5.00 / $22.50, 캐시 읽기 $0.50");
    // Nova: up to four decimals, and the official $0.00 cache write is shown.
    expect(line(cell(ko, "nova-2-lite", "us"), "cache")).toBe("캐시 읽기 $0.0825, 쓰기 $0.00");
    expect(line(cell(ko, "nova-2-lite", "us"), "long")).toBeNull();

    const en = render("en");
    expect(line(cell(en, "claude-opus-5-5", "global"), "cache")).toBe("Cache read $0.20, write $5.00, 1h write $8.00");
    expect(line(cell(en, "gpt-6-astra", "global"), "long")).toBe("Long context $20.00 / $75.00, cache read $2.00, write $25.00");
  });

  test("가격 줄, 캐시 줄, 긴 컨텍스트 줄, 배지 순서이고 In Region 원소마다 따로 있다", () => {
    const inRegion = cell(render("ko"), "gpt-5.4", "in_region");
    const first = inRegion.slice(0, inRegion.indexOf("data-price-line", inRegion.indexOf("data-price-line") + 1));
    const at = ["$2.75 / $16.50", "data-cache-line", "data-long-line", 'data-badge="pending"'].map((needle) => first.indexOf(needle));
    expect(at.every((i) => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    expect(count(inRegion, "data-cache-line")).toBe(2);
    expect(count(inRegion, "data-long-line")).toBe(2);
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
    expect(html).not.toContain("수동 메모"); // the promotion cites the OpenAI pricing page, not a manual note
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

  test("세 표는 같은 고정 열 폭(빈 열도 <col> 5개), 표마다 이름(caption)이 있고 단위 범례는 표 위에 한 번", () => {
    const html = render("ko");
    const tables = html.match(/<table [^>]*>.*?<\/colgroup>/g) ?? [];
    expect(tables).toHaveLength(3);
    const layout = (table: string) => table.replace(/<caption[^>]*>.*?<\/caption>/, "");
    expect(new Set(tables.map(layout)).size).toBe(1);
    for (const table of tables) expect(count(table, "<col ")).toBe(5);
    const first = tables[0] ?? "";
    expect(first).toContain("table-fixed");
    expect(first).toContain("min-w-[800px]");
    expect(first).toContain('<col class="w-36"/>');
    expect(count(first, '<col class="w-[calc((100%_-_9rem)/4)]"/>')).toBe(4);
    expect(html).toContain('<caption class="sr-only">Anthropic Claude 단가 (입력 / 출력, 1M 토큰당 USD)</caption>');
    expect(render("en")).toContain('<caption class="sr-only">OpenAI prices (input / output, USD per 1M tokens)</caption>');
    expect(count(html, "data-unit-legend")).toBe(1);
    expect(html.indexOf("data-unit-legend")).toBeLessThan(html.indexOf("<table"));
    const legend = (markup: string) => /data-unit-legend="true"[^>]*>(.*?)<\/p>/.exec(markup)?.[1] ?? "";
    expect(plain(legend(html))).toBe("각 단가 셀: 입력 / 출력, 1M 토큰당 USD. 둘째 줄: 프롬프트 캐싱. GPT 셋째 줄: 긴 컨텍스트");
    expect(plain(legend(render("en"))))
      .toBe("Each price cell: input / output, USD per 1M tokens. Second line: prompt caching. Third line on GPT rows: long context");
    for (const term of ["입력 / 출력", "1M 토큰당 USD", "프롬프트 캐싱", "긴 컨텍스트"]) {
      expect(legend(html)).toContain(`<span class="whitespace-nowrap font-medium text-gray-300">${term}</span>`);
    }
    for (const term of ["input / output", "USD per 1M tokens", "prompt caching", "long context"]) {
      expect(legend(render("en"))).toContain(`<span class="whitespace-nowrap font-medium text-gray-300">${term}</span>`);
    }
    expect(render("ko", null, { ...pricingFixture, families: [] })).not.toContain("data-unit-legend");
  });

  test("고정 모델 열은 불투명 배경과 오른쪽 구분선", () => {
    const html = render("ko");
    const sticky = html.match(/<th scope="row" class="([^"]*)"/)?.[1] ?? "";
    for (const name of ["sticky", "left-0", "bg-gray-900", "border-r", "border-r-gray-800"]) expect(sticky.split(" ")).toContain(name);
    expect(html).toMatch(/<th scope="col" class="sticky left-0 z-10 border-r border-r-gray-800 bg-gray-900/);
  });

  test("각주는 #ref-n 링크, 참고 자료가 같은 id, 강조는 하나, OpenAI 공식 요금 문서는 openai_doc", () => {
    const html = render("ko", 7);
    expect(html).toContain('href="#ref-7"');
    expect(html).toContain('aria-label="참고 자료 7"');
    for (const ref of pricingFixture.references) expect(html).toContain(`id="ref-${ref.n}"`);
    expect(count(html, 'data-highlighted="true"')).toBe(1);
    expect(html).toMatch(/id="ref-7"[^>]*data-highlighted="true"/);
    expect(html).toMatch(/id="ref-4" data-kind="openai_doc"/);
    expect(plain(html)).toContain("OpenAI API 요금 (Standard) ↗");
    expect(html).toContain('href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noopener noreferrer"');
  });

  test("참고 자료는 1..N 연속 번호이고 모두 페이지의 각주가 인용한다 (인용되지 않는 공식 페이지는 없다)", () => {
    const html = render("ko");
    const listed = [...html.matchAll(/<li id="ref-(\d+)"/g)].map((match) => Number(match[1]));
    expect(listed).toEqual(pricingFixture.references.map((_, i) => i + 1));
    const cited = new Set([...html.matchAll(/href="#ref-(\d+)"/g)].map((match) => Number(match[1])));
    expect(listed.filter((n) => !cited.has(n))).toEqual([]);
    expect(pricingFixture.references.map((reference) => reference.kind)).not.toContain("official_page");
  });

  test("다운로드 링크는 현재 언어의 export download 링크", () => {
    for (const format of ["csv", "md", "json"]) {
      expect(render("ko")).toContain(`href="/api/pricing/export?format=${format}&amp;lang=ko" download=""`);
    }
    expect(render("en")).toContain('href="/api/pricing/export?format=csv&amp;lang=en" download=""');
  });

  test("면책 문구 두 번, 참고 사항 9개(마침표 없음), 동기화 상태와 검토 대기 수", () => {
    const html = render("ko");
    expect(count(html, pricingFixture.disclaimer.ko)).toBe(2);
    expect(count(render("en"), pricingFixture.disclaimer.en)).toBe(2);
    const notes = (markup: string) => {
      const list = /<ol class="list-decimal[^"]*">(.*?)<\/ol>/.exec(markup)?.[1] ?? "";
      return [...list.matchAll(/<li>(.*?)<\/li>/g)].map((match) => plain(match[1]));
    };
    expect(notes(html)).toEqual(NOTES_KO);
    expect(notes(render("en"))).toEqual(NOTES_EN);
    expect(NOTES_KO).toHaveLength(9);
    // The GPT channel note comes right after the Global CRIS note.
    expect(notes(html)[2]).toMatch(/^GPT의 AWS Bedrock - US CRIS와 In Region 단가는 같다\./);
    expect(html).toContain("완료");
    expect(html).toContain("검토 대기 1건");
    expect(html).toContain("마지막 공식 단가 동기화: ");
    expect(render("en")).toContain("Last official price sync: ");
    expect(render("en", null, { ...pricingFixture, last_sync: null, pending_review: 0 })).toContain("No official price sync has run yet");
  });

  test("배지 설명은 title 툴팁이 아니라 배지 옆 글자, 프로모션은 OpenAI 공식 요금 문서 참고 자료로 각주", () => {
    const html = render("ko");
    expect(html).not.toMatch(/data-badge="[a-z_]+"[^>]*title=/);
    expect(plain(cell(html, "gpt-5.4", "in_region"))).toContain("새 값 $3.00 / $18.00");
    expect(cell(html, "gpt-5.4", "in_region")).toMatch(/data-badge-detail="pending"[^>]*><span class="tabular-nums">새 값 <span class="whitespace-nowrap">\$3\.00 \/ \$18\.00<\/span><\/span>/);
    expect(plain(cell(html, "claude-fable-5-1", "us"))).toContain("공식 출처 확인 2026-09-20");
    expect(plain(cell(render("en"), "claude-fable-5-1", "us"))).toContain("Confirmed at source 2026-09-20");
    expect(cell(html, "nova-2-lite", "us")).toMatch(/data-badge-detail="unverified"[^>]*><span[^>]*>초기값<\/span>/);
    // The promotion note names the OpenAI list price, Global CRIS and In Region.
    const sol = html.slice(html.indexOf('data-family="gpt-5.6-sol"'), html.indexOf("</tr>", html.indexOf('data-family="gpt-5.6-sol"')));
    expect(count(sol, 'data-badge="promo"')).toBe(3);
    const promo = cell(html, "gpt-5.6-sol", "in_region");
    expect(plain(promo)).toContain("프로모션 이전 단가 $5.50 / $33.00");
    expect(promo).toMatch(/data-badge-detail="promo"[^>]*>.*href="#ref-4"/);
    expect(plain(cell(html, "gpt-5.6-sol", "openai_list"))).toContain("프로모션 이전 단가 $5.00 / $30.00[4]");
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

  test("면책 상자의 Anthropic, OpenAI 요금 링크, 참고 자료 확인일, 검토 대기 0건이면 숨김", () => {
    const html = render("ko");
    const box = html.slice(html.indexOf('data-disclaimer="top"'), html.indexOf("</div>", html.indexOf('data-disclaimer="top"')));
    expect(box).toContain('href="https://platform.claude.com/docs/en/about-claude/pricing"');
    expect(box).toContain('href="https://developers.openai.com/api/docs/pricing"');
    expect(box.indexOf("Anthropic 요금")).toBeLessThan(box.indexOf("OpenAI 요금"));
    expect(plain(render("en").slice(render("en").indexOf('data-disclaimer="top"')))).toContain("OpenAI pricing ↗");
    expect(html).toContain("확인일 2026-09-26");
    const none = render("en", null, { ...pricingFixture, pending_review: 0 });
    expect(none).not.toContain("data-pending-count");
    expect(none).not.toContain("pending review");
  });
});
