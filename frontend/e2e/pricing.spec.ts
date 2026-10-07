import { expect, test } from "@playwright/test";
import { mockApi, pricingFixture } from "./fixtures";

const DISCLAIMER_KO = pricingFixture.disclaimer.ko;
const EXPORT_EXT = { csv: "csv", md: "md", json: "json" } as const;
const BEDROCK_COLUMNS = ["AWS Bedrock - Global CRIS", "AWS Bedrock - US CRIS", "AWS Bedrock - In Region"];

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  // The promotion badge depends on today's date (min_until 2026-11-21); timers keep running.
  await page.clock.setFixedTime(new Date("2026-09-26T12:00:00Z"));
});

test("unit prices render the backend table, badges and both disclaimers", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { name: "비용 단가", level: 1, exact: true })).toBeVisible();
  await expect(page).toHaveTitle("비용 단가 | LLM Monitor");

  const nav = page.getByRole("navigation", { name: "주요 메뉴" });
  await expect(nav.getByRole("link", { name: "비용 단가", exact: true })).toHaveAttribute("aria-current", "page");
  const labels = await nav.getByRole("link").allTextContents();
  expect(labels.indexOf("비용 단가")).toBe(labels.indexOf("대시보드") + 1);  // v2.31.2: right after the dashboard

  const disclaimer = page.getByRole("note", { name: "면책 안내" });
  await expect(disclaimer).toContainText(DISCLAIMER_KO);
  await expect(disclaimer.getByRole("link", { name: "Amazon Bedrock 요금" })).toHaveAttribute("href", "https://aws.amazon.com/bedrock/pricing/");
  await expect(disclaimer.getByRole("link", { name: "OpenAI 요금" })).toHaveAttribute("href", "https://developers.openai.com/api/docs/pricing");
  await expect(page.locator('[data-disclaimer="bottom"]')).toHaveText(DISCLAIMER_KO);
  await expect(page.locator("[data-last-sync]")).toContainText("마지막 공식 단가 동기화: ");
  await expect(page.locator("[data-last-sync]")).toContainText("완료");
  await expect(page.locator("[data-pending-count]")).toHaveText("검토 대기 1건");

  await expect(page.getByRole("main").getByRole("heading", { level: 2 }))
    .toHaveText(["Anthropic Claude", "OpenAI", "Amazon Nova", "참고 사항", "참고 자료"]);
  await expect(page.getByRole("region", { name: "OpenAI 단가 표" }).getByRole("rowheader"))
    .toHaveText(["GPT 6 Astra", "GPT 5.6 Sol", "GPT 5.4"]);
  await expect(page.getByRole("region", { name: "Anthropic Claude 단가 표" }).getByRole("columnheader"))
    .toHaveText(["모델", "Claude Platform on AWS", ...BEDROCK_COLUMNS]);
  await expect(page.getByRole("region", { name: "OpenAI 단가 표" }).getByRole("columnheader"))
    .toHaveText(["모델", "OpenAI 공식 가격", ...BEDROCK_COLUMNS]);
  // Amazon Nova's first column is blank: an empty, aria-hidden cell in the header row and in every body row.
  const nova = page.getByRole("region", { name: "Amazon Nova 단가 표" });
  await expect(nova.getByRole("columnheader")).toHaveText(["모델", ...BEDROCK_COLUMNS]);
  const novaRows = await nova.locator("tbody tr").count();
  await expect(nova.locator('thead [data-tier="none"]')).toHaveCount(1);
  await expect(nova.locator('tbody [data-tier="none"]')).toHaveCount(novaRows);
  expect(await nova.locator('[data-tier="none"]').allTextContents()).toEqual(Array(novaRows + 1).fill(""));
  expect(await nova.locator('[data-tier="none"]').evaluateAll((cells) => cells.map((c) => c.getAttribute("aria-hidden"))))
    .toEqual(Array(novaRows + 1).fill("true"));
  await expect(page.locator('main [data-tier="none"]')).toHaveCount(novaRows + 1);
  // The unit is said once above the tables, and each table's caption names it with the unit.
  await expect(page.locator("[data-unit-legend]"))
    .toHaveText("각 단가 셀: 입력 / 출력, 1M 토큰당 USD. 둘째 줄: 프롬프트 캐싱. GPT와 Claude Haiku 5.5 셋째 줄: 긴 컨텍스트");
  for (const provider of ["Anthropic Claude", "OpenAI", "Amazon Nova"]) {
    await expect(page.getByRole("table", { name: `${provider} 단가 (입력 / 출력, 1M 토큰당 USD)`, exact: true })).toBeVisible();
  }
  // Fixed layout: the three provider tables put every column (Nova's blank one included) at the same x, with four
  // equal price columns.
  const columns = await page.locator("main table").evaluateAll((tables) => tables.map((table) =>
    [...table.querySelectorAll("thead tr > *")].map((cell) => {
      const box = cell.getBoundingClientRect();
      return [Math.round(box.left), Math.round(box.width)];
    })));
  expect(columns).toHaveLength(3);
  expect(columns[0]).toHaveLength(5);
  expect(columns[1]).toEqual(columns[0]);
  expect(columns[2]).toEqual(columns[0]);
  const priceWidths = columns[0].slice(1).map(([, width]) => width);
  expect(Math.max(...priceWidths) - Math.min(...priceWidths)).toBeLessThanOrEqual(1);

  const opus = page.locator('tr[data-family="claude-opus-5-5"]');
  await expect(opus.locator('td[data-tier="cp"]')).toContainText("$4.00 / $20.00");
  await expect(opus.locator('td[data-tier="us"]')).toContainText("$4.40 / $22.00");
  await expect(opus.locator('td[data-tier="in_region"]')).toHaveText("—단가 없음");
  // Second line: prompt caching (Claude 5-minute write, 1-hour write). Claude rows have no long-context line.
  await expect(opus.locator('td[data-tier="global"] [data-cache-line]')).toHaveText("캐시 읽기 $0.20, 쓰기 $5.00, 1시간 쓰기 $8.00");
  await expect(opus.locator('td[data-tier="us"] [data-cache-line]')).toHaveText("캐시 읽기 $0.22, 쓰기 $5.50, 1시간 쓰기 $8.80");
  await expect(page.locator('tr[data-family^="claude-"] [data-long-line]')).toHaveCount(0);

  // The OpenAI table starts with OpenAI's own list price; GPT rows add a third line for long context.
  const astra = page.locator('tr[data-family="gpt-6-astra"]');
  await expect(astra.locator('td[data-tier="openai_list"] [data-price-line]')).toContainText("$10.00 / $50.00");
  await expect(astra.locator('td[data-tier="openai_list"] [data-cache-line]')).toHaveText("캐시 읽기 $1.00, 쓰기 $12.50");
  await expect(astra.locator('td[data-tier="openai_list"] [data-long-line]'))
    .toHaveText("긴 컨텍스트 $20.00 / $75.00, 캐시 읽기 $2.00, 쓰기 $25.00");
  await expect(astra.locator('td[data-tier="us"] [data-long-line]')).toHaveText("긴 컨텍스트 $22.00 / $82.50, 캐시 읽기 $2.20, 쓰기 $27.50");
  await expect(page.locator('section[aria-labelledby="pricing-openai"] [data-tier="cp"]')).toHaveCount(0);
  const novaUs = page.locator('tr[data-family="nova-2-lite"] td[data-tier="us"]');
  await expect(novaUs.locator("[data-cache-line]")).toHaveText("캐시 읽기 $0.0825, 쓰기 $0.00");
  await expect(novaUs.locator("[data-long-line]")).toHaveCount(0);

  const gpt54 = page.locator('tr[data-family="gpt-5.4"] td[data-tier="in_region"] [data-price-line]');
  await expect(gpt54).toHaveCount(2);
  await expect(gpt54.nth(0)).toContainText("$2.75 / $16.50 us-east-1, us-east-2");
  await expect(gpt54.nth(1)).toContainText("$2.50 / $15.00 us-west-2");
  await expect(gpt54.nth(0).locator("[data-long-line]")).toHaveText("긴 컨텍스트 $5.50 / $24.75, 캐시 읽기 $0.55");
  // Badge explanations are visible text next to the badge (touch and keyboard users never see a title tooltip).
  await expect(page.locator("[data-badge][title]")).toHaveCount(0);
  await expect(gpt54.nth(0).locator('[data-badge-detail="pending"]')).toBeVisible();
  await expect(gpt54.nth(0).locator('[data-badge-detail="pending"]')).toHaveText("새 값 $3.00 / $18.00");

  const fableUs = page.locator('tr[data-family="claude-fable-5-1"] td[data-tier="us"]');
  await expect(fableUs.locator('[data-badge="unverified"]')).toContainText("자동 확인 안 됨");
  await expect(fableUs.locator('[data-badge-detail="unverified"]')).toHaveText("공식 출처 확인 2026-09-20");
  await expect(page.locator('tr[data-family="nova-2-lite"] [data-badge-detail="unverified"]')).toHaveText("초기값");
  // The promotion names the OpenAI list price, Global CRIS and In Region.
  const promo = page.locator('tr[data-family="gpt-5.6-sol"] [data-badge="promo"]');
  await expect(promo).toHaveCount(3);
  await expect(promo.first()).toContainText("프로모션(최소 2026-11-21까지)");
  const promoDetail = page.locator('tr[data-family="gpt-5.6-sol"] td[data-tier="in_region"] [data-badge-detail="promo"]');
  await expect(promoDetail).toContainText("프로모션 이전 단가 $5.50 / $33.00");
  // The promotion's source is the OpenAI pricing page reference, one footnote away.
  await expect(promoDetail.getByRole("link", { name: "참고 자료 4" })).toHaveAttribute("href", "#ref-4");
  await expect(page.locator("[data-scroll-hint]")).toHaveCount(0);

  const notes = page.getByRole("region", { name: "참고 사항" }).getByRole("listitem");
  await expect(notes).toHaveText([
    "단가는 USD, 1M 토큰당, Standard 등급 기준이다",
    "AWS Bedrock - Global CRIS 단가는 같은 모델의 US CRIS, In Region 단가와 다를 수 있다",
    "GPT의 AWS Bedrock - US CRIS와 In Region 단가는 같다. AWS가 두 채널 모두 OpenAI 공식 가격에 10%를 더하고, Global CRIS는 OpenAI 공식 가격과 같다",
    "캐시 쓰기는 Claude의 5분 캐시, OpenAI 공식 문서의 cache writes, Nova의 캐시 쓰기 단가이고, 1시간 쓰기는 Claude의 1시간 캐시 단가다",
    "긴 컨텍스트 요금은 GPT에서는 OpenAI가 정한 짧은 컨텍스트 한도(GPT 5.4, 5.5는 272K)를 넘는 요청에, Claude Haiku 5.5에서는 100K 토큰을 넘는 프롬프트에 적용된다",
    "OpenAI 공식 가격은 OpenAI 직접 API 단가이며 비용 계산에 쓰지 않는다",
    "캐시와 긴 컨텍스트 단가는 표시만 하며, 비용 화면은 입력과 출력 단가로 계산한다",
    "batch, flex, priority(fast) 단가는 포함하지 않는다",
    "비용 화면은 각 프로브 시각의 단가로 계산한다",
  ]);
  const references = page.getByRole("region", { name: "참고 자료" }).getByRole("listitem");
  await expect(references).toHaveCount(pricingFixture.references.length);
  await expect(page.locator("#ref-1").getByRole("link")).toHaveAttribute("rel", "noopener noreferrer");
  await expect(page.locator("#ref-4")).toHaveAttribute("data-kind", "openai_doc");
  await expect(page.locator("#ref-4")).toContainText("OpenAI API 요금 (Standard)");
  await expect(page.locator("#ref-4").getByRole("link")).toHaveAttribute("href", "https://developers.openai.com/api/docs/pricing");
  await expect(page.locator('[data-kind="manual_note"]')).toHaveCount(0);
  // Every listed reference is cited by at least one footnote on the page, and the numbers run 1..N.
  const listed = await references.evaluateAll((items) => items.map((item) => Number(item.id.replace("ref-", ""))));
  expect(listed).toEqual(pricingFixture.references.map((_, i) => i + 1));
  const cited = await page.locator('main a[href^="#ref-"]').evaluateAll((links) =>
    [...new Set(links.map((link) => Number(link.getAttribute("href")!.replace("#ref-", ""))))]);
  expect(listed.filter((n) => !cited.includes(n))).toEqual([]);
  await expect(page.locator('[data-kind="official_page"]')).toHaveCount(0);
  // The top links box keeps the three official pricing pages.
  await expect(disclaimer.getByRole("link")).toHaveText(["Amazon Bedrock 요금 ↗", "Anthropic 요금 ↗", "OpenAI 요금 ↗"]);
});

test("Unit Prices sits right after the dashboard in the header menu (v2.31.2)", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/pricing");
  const nav = page.getByRole("navigation", { name: "주요 메뉴" });
  await expect(nav.getByRole("link").nth(0)).toHaveText("대시보드");
  await expect(nav.getByRole("link").nth(1)).toHaveText("비용 단가");
  await expect(nav.getByRole("link").nth(1)).toHaveAttribute("aria-current", "page");
  await expect(nav.getByRole("link").nth(2)).toHaveText("모델 탐색");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "메뉴 열기" }).click();
  const mobile = page.getByRole("navigation", { name: "모바일 메뉴" });
  await expect(mobile.getByRole("link").nth(0)).toHaveText("대시보드");
  await expect(mobile.getByRole("link").nth(1)).toHaveText("비용 단가");
});

test("the model-ID toggle lists each price's model IDs, by keyboard too", async ({ page }) => {
  await page.goto("/pricing");
  const toggle = page.getByRole("button", { name: "모델 ID 보기", exact: true });
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("[data-model-ids]")).toHaveCount(0);

  await toggle.focus();
  await page.keyboard.press("Enter");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  const ids = page.locator('tr[data-family="gpt-5.4"] td[data-tier="in_region"] [data-price-line]').nth(0).locator("[data-model-ids]");
  await expect(ids).toBeVisible();
  await expect(ids.locator("span")).toHaveText(["openai:us-east-1:openai.gpt-5.4", "openai:us-east-2:openai.gpt-5.4"]);
  await expect(page.locator('tr[data-family="claude-opus-5-5"] td[data-tier="cp"] [data-model-ids]')).toHaveText("anthropic:claude-opus-5-5");

  await page.keyboard.press("Space");
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator("[data-model-ids]")).toHaveCount(0);
});

test("a promotion past its minimum date asks to check whether it ended", async ({ page }) => {
  await page.clock.setFixedTime(new Date("2026-11-22T00:00:00Z"));
  await page.goto("/pricing");
  const sol = page.locator('tr[data-family="gpt-5.6-sol"]');
  await expect(sol.locator('[data-badge="promo_check"]')).toHaveCount(3);
  await expect(sol.locator('[data-badge="promo_check"]').first()).toContainText("프로모션 종료 여부 확인 필요");
  await expect(sol.locator('[data-badge="promo"]')).toHaveCount(0);
});

test("a footnote jumps to its reference and highlights it for 1.5 seconds", async ({ page }) => {
  await page.goto("/pricing");
  await page.locator('tr[data-family="gpt-5.4"]').getByRole("link", { name: "참고 자료 7" }).first().click();
  await expect(page).toHaveURL(/#ref-7$/);
  const reference = page.locator("#ref-7");
  await expect(reference).toHaveAttribute("data-highlighted", "true");
  await expect(reference).toBeInViewport();
  const header = (await page.locator("header").boundingBox())!;
  expect((await reference.boundingBox())!.y).toBeGreaterThanOrEqual(header.y + header.height);
  await expect(reference).toHaveAttribute("data-highlighted", "false", { timeout: 3000 });
});

test("download links point at the export endpoint in the current language", async ({ page }) => {
  // Chromium sends <a download> requests from the download manager, outside Playwright routing
  // (checked on the dev host), so the test fetches each link's href through the intercepted route.
  const requested: string[] = [];
  await page.route("**/api/pricing/export?*", (route) => {
    const url = new URL(route.request().url());
    requested.push(`${url.searchParams.get("format")}:${url.searchParams.get("lang")}`);
    const ext = EXPORT_EXT[url.searchParams.get("format") as keyof typeof EXPORT_EXT];
    return route.fulfill({
      status: 200,
      contentType: "text/plain; charset=utf-8",
      headers: { "Content-Disposition": `attachment; filename="llm-monitor-unit-prices-2026-09-26.${ext}"` },
      body: DISCLAIMER_KO,
    });
  });
  await page.goto("/pricing");
  const group = page.getByRole("group", { name: "가격표 내려받기" });
  for (const [label, format] of [["CSV", "csv"], ["Markdown", "md"], ["JSON", "json"]] as const) {
    const link = group.getByRole("link", { name: label, exact: true });
    await expect(link).toHaveAttribute("href", `/api/pricing/export?format=${format}&lang=ko`);
    await expect(link).toHaveAttribute("download", "");
    const disposition = await link.evaluate(async (element) => {
      const response = await fetch((element as HTMLAnchorElement).href);
      return response.headers.get("content-disposition");
    });
    expect(disposition).toBe(`attachment; filename="llm-monitor-unit-prices-2026-09-26.${EXPORT_EXT[format]}"`);
  }
  expect(requested).toEqual(["csv:ko", "md:ko", "json:ko"]);

  await page.locator('header button[lang="en"]:visible').click();
  const english = page.getByRole("group", { name: "Download price list" });
  await expect(english.getByRole("link", { name: "CSV", exact: true })).toHaveAttribute("href", "/api/pricing/export?format=csv&lang=en");
  await expect(page.getByRole("note", { name: "Disclaimer" })).toContainText(pricingFixture.disclaimer.en);
});

test("a 375px phone scrolls only the price table, with the model column pinned", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/pricing");
  const table = page.getByRole("region", { name: "OpenAI 단가 표" });
  await expect(table.getByRole("rowheader").first()).toBeVisible();
  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
    await expect.poll(() => page.evaluate(() => {
      const root = document.scrollingElement!;
      return root.scrollWidth <= root.clientWidth;
    })).toBe(true);
  }
  expect(await table.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  // Overlay scrollbars stay hidden until a scroll, and only the first price column fits (Claude Platform on AWS,
  // OpenAI official price, or Nova's blank column), so the AWS Bedrock prices are off screen: a hint above each table
  // and a fade on its right edge say it scrolls.
  const section = page.locator('section[aria-labelledby="pricing-openai"]');
  const hint = section.locator("[data-scroll-hint]");
  await expect(hint).toBeVisible();
  await expect(hint).toHaveText("→ 표를 옆으로 스크롤하면 AWS Bedrock 단가가 보입니다");
  await expect(section.locator("[data-scroll-fade]")).toHaveCount(1);
  await expect(page.locator("[data-scroll-hint]")).toHaveCount(3);
  await table.evaluate((element) => { element.scrollLeft = element.scrollWidth; });
  await expect(hint).toBeHidden();
  await expect(section.locator("[data-scroll-fade]")).toHaveCount(0);
  // Hidden, not removed: the table does not jump up when the hint goes away.
  expect(await hint.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThan(0);
  const box = (await table.boundingBox())!;
  const model = (await table.getByRole("rowheader").first().boundingBox())!;
  expect(Math.abs(model.x - box.x)).toBeLessThan(2);
  // The pinned model column is opaque with a divider in both themes, so scrolled prices never show beside the name.
  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
    const sticky = await table.getByRole("rowheader").first().evaluate((element) => {
      const style = getComputedStyle(element);
      return { divider: style.borderRightWidth, background: style.backgroundColor };
    });
    expect(sticky.divider).toBe("1px");
    expect(sticky.background).toMatch(/^rgb\(\d+, \d+, \d+\)$/);
  }
  await page.evaluate(() => document.documentElement.classList.remove("light"));
  // No token wraps inside: region ids, price pairs, cache and long-context items, the parts of two-part column titles,
  // the sync time, short badges and the pending count stay whole.
  const split = await page.evaluate(() => {
    const inline = [...document.querySelectorAll(
      "[data-regions] > span, [data-price-line] > span:first-child, [data-cache-line] > span, [data-long-line] > span, thead th > span, [data-last-sync] time",
    )];
    const boxes = [...document.querySelectorAll('[data-badge="unverified"], [data-badge="pending"], [data-pending-count]')];
    return [
      ...inline.filter((element) => element.getClientRects().length > 1),
      ...boxes.filter((element) => element.getBoundingClientRect().height > 2 * parseFloat(getComputedStyle(element).lineHeight)),
    ].map((element) => element.textContent);
  });
  expect(split).toEqual([]);
  // Nothing in a price cell or a column title spills into the next column.
  const spilled = await page.locator("main td, main thead th").evaluateAll((cells) => cells
    .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
    .map((cell) => cell.closest("tr")?.getAttribute("data-family") ?? cell.textContent));
  expect(spilled).toEqual([]);

  await page.locator("header button[aria-controls]").click();
  await expect(page.getByRole("navigation", { name: "모바일 메뉴" }).getByRole("link", { name: "비용 단가", exact: true }))
    .toHaveAttribute("aria-current", "page");
});

test("a 390px phone in English shows the new columns, cache and long-context lines without page overflow", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("lang", "en"));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { name: "Unit Prices", level: 1, exact: true })).toBeVisible();
  await expect(page.getByRole("main").getByRole("heading", { level: 2 }))
    .toHaveText(["Anthropic Claude", "OpenAI", "Amazon Nova", "Notes", "References"]);
  await expect(page.getByRole("region", { name: "Anthropic Claude price table" }).getByRole("columnheader"))
    .toHaveText(["Model", "Claude Platform on AWS", ...BEDROCK_COLUMNS]);
  await expect(page.getByRole("region", { name: "OpenAI price table" }).getByRole("columnheader"))
    .toHaveText(["Model", "OpenAI official price", ...BEDROCK_COLUMNS]);
  await expect(page.getByRole("region", { name: "Amazon Nova price table" }).getByRole("columnheader"))
    .toHaveText(["Model", ...BEDROCK_COLUMNS]);
  await expect(page.locator("[data-unit-legend]"))
    .toHaveText("Each price cell: input / output, USD per 1M tokens. Second line: prompt caching. Third line on GPT and Claude Haiku 5.5 rows: long context");
  await expect(page.locator('tr[data-family="claude-opus-5-5"] td[data-tier="global"] [data-cache-line]'))
    .toHaveText("Cache read $0.20, write $5.00, 1h write $8.00");
  await expect(page.locator('tr[data-family="gpt-6-astra"] td[data-tier="global"] [data-long-line]'))
    .toHaveText("Long context $20.00 / $75.00, cache read $2.00, write $25.00");
  await expect(page.locator('section[aria-labelledby="pricing-amazon"] [data-scroll-hint]'))
    .toHaveText("→ Scroll the table sideways for the AWS Bedrock prices");
  await expect(page.getByRole("region", { name: "Notes" }).getByRole("listitem")).toHaveCount(9);
  await expect(page.getByRole("region", { name: "Notes" }).getByRole("listitem").nth(2))
    .toHaveText("GPT prices on AWS Bedrock - US CRIS and In Region are the same: AWS adds 10% to the OpenAI official price on both, and Global CRIS equals the OpenAI official price");
  await expect(page.getByRole("region", { name: "Notes" }).getByRole("listitem").nth(5))
    .toHaveText("The OpenAI official price is OpenAI's direct API price and is not used for cost calculations");

  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
    await expect.poll(() => page.evaluate(() => {
      const root = document.scrollingElement!;
      return root.scrollWidth <= root.clientWidth;
    })).toBe(true);
  }
  await page.evaluate(() => document.documentElement.classList.remove("light"));
  // Only two-part column titles have unbreakable parts ("AWS Bedrock -" / "Global CRIS"); a title without " - "
  // ("Claude Platform on AWS", "OpenAI official price") is plain text that wraps between words.
  const titleParts = ["AWS Bedrock -", "Global CRIS", "AWS Bedrock -", "US CRIS", "AWS Bedrock -", "In Region"];
  expect(await page.locator("main thead th > span").allTextContents()).toEqual([...titleParts, ...titleParts, ...titleParts]);
  const split = await page.evaluate(() => [...document.querySelectorAll("[data-cache-line] > span, [data-long-line] > span, main thead th > span")]
    .filter((element) => element.getClientRects().length > 1)
    .map((element) => element.textContent));
  expect(split).toEqual([]);
  const spilled = await page.locator("main td, main thead th").evaluateAll((cells) => cells
    .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
    .map((cell) => cell.closest("tr")?.getAttribute("data-family") ?? cell.textContent));
  expect(spilled).toEqual([]);

  // A larger text size (root font size 110%, as a browser font-size setting gives) while the table keeps its 800px
  // minimum: no column title spills into the next column.
  await page.evaluate(() => { document.documentElement.style.fontSize = "110%"; });
  const titleSpilled = await page.locator("main thead th").evaluateAll((cells) => cells
    .filter((cell) => cell.scrollWidth > cell.clientWidth + 1)
    .map((cell) => `${cell.textContent} ${cell.scrollWidth}/${cell.clientWidth}`));
  expect(titleSpilled).toEqual([]);
});

test("a failed price request offers a retry and is not shown as an empty table", async ({ page }) => {
  let fail = true;
  await page.route("**/api/pricing", (route) => fail
    ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
    : route.fallback());
  await page.goto("/pricing");
  const error = page.getByRole("alert").filter({ hasText: "비용 단가" });
  await expect(error).toBeVisible();
  await expect(page.getByText("표시할 단가가 없습니다.", { exact: true })).toHaveCount(0);
  fail = false;
  await error.getByRole("button", { name: "다시 시도" }).click();
  await expect(page.locator('tr[data-family="claude-opus-5-5"]')).toBeVisible();
});

test("Model Explorer cards and details use prices from /api/pricing", async ({ page }) => {
  await page.route("**/api/models", (route) => route.fulfill({ json: [
    { id: "global.anthropic.claude-fable-5-1", name: "Bedrock Claude Fable 5.1 (Global)" },
    { id: "openai:us:us.openai.gpt-6-sol", name: "OpenAI GPT 6 Sol (US)" },
  ] }));
  await page.route("**/api/pricing", (route) => route.fulfill({ json: {
    ...pricingFixture,
    models: { "global.anthropic.claude-fable-5-1": { input: 12.34, output: 56.78, verification: "verified" } },
  } }));
  await page.goto("/models");
  const fable = page.getByRole("button", { name: "Bedrock Claude Fable 5.1 (Global)", exact: true });
  await expect(fable).toContainText("$12.34 / $56.78 (1M 토큰당 입력/출력)");
  await expect(page.getByRole("button", { name: "OpenAI GPT 6 Sol (US)", exact: true })).toContainText("단가 정보 없음");
  await fable.click();
  await expect(page.getByRole("dialog", { name: "Bedrock Claude Fable 5.1 (Global)" })).toContainText("입력 $12.34 / 출력 $56.78");
});

test("the cost methodology links to the unit price page", async ({ page }) => {
  await page.goto("/cost");
  const link = page.locator("[data-cost-methodology]").getByRole("link", { name: "비용 단가", exact: true });
  await expect(link).toHaveAttribute("href", "/pricing");
  await link.click();
  await expect(page).toHaveURL(/\/pricing$/);
  await expect(page.getByRole("heading", { name: "비용 단가", level: 1, exact: true })).toBeVisible();
});
