import { expect, test, type Page } from "@playwright/test";
import type { PricingChangeItem, PricingChanges } from "../src/lib/types";
import { mockApi, pricingFixture } from "./fixtures";

// /pricing run-to-run changes (v2.40.0, ADR-035): the banner's three states, an item that scrolls to and highlights its
// cell, the cell badge, and a removed channel that stays text. pricing.spec.ts covers the table itself.

function item(over: Partial<PricingChangeItem>): PricingChangeItem {
  return {
    model_id: "us.anthropic.claude-opus-5-5", family_key: "claude-opus-5-5", family: "Claude Opus 5.5", provider: "anthropic",
    tier: "us", region: null, kind: "price", field: "cache_read", before: 0.44, after: 0.22, ...over,
  };
}

const LIST: PricingChanges = {
  available: true, run_id: 13, finished_at: "2026-09-26T15:00:31Z", previous_run_id: 12, previous_finished_at: "2026-09-26T03:00:29Z",
  items: [
    item({}),
    item({ model_id: "openai:global:global.openai.gpt-6-astra", family_key: "gpt-6-astra", family: "GPT 6 Astra", provider: "openai",
           tier: "global", kind: "pending", field: "input", before: null, after: 11 }),
    item({ model_id: "global.anthropic.claude-gone", family_key: "claude-gone", family: "Claude Gone", tier: "global",
           kind: "channel", field: null, before: "present", after: null }),
  ],
};

async function withChanges(page: Page, changes: PricingChanges) {
  await page.route("**/api/pricing", (route) => route.fulfill({ json: { ...pricingFixture, changes } }));
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.clock.setFixedTime(new Date("2026-09-26T12:00:00Z"));
});

test("before two snapshot runs the banner says changes start with the next sync", async ({ page }) => {
  await withChanges(page, { available: false, run_id: 13 });
  await page.goto("/pricing");
  await expect(page.locator('[data-price-changes="unavailable"]')).toHaveText("변경 비교는 다음 동기화부터 표시됩니다.");
});

test("no change is a sentence, not an empty space", async ({ page }) => {
  await withChanges(page, { ...LIST, items: [] });
  await page.goto("/pricing");
  await expect(page.locator('[data-price-changes="none"]')).toContainText("이전 동기화(#12, ");
  await expect(page.locator('[data-price-changes="none"]')).toContainText("대비 변경 없음.");
});

test("an older backend without changes shows no banner", async ({ page }) => {
  await page.goto("/pricing");
  await expect(page.getByRole("heading", { name: "비용 단가", level: 1, exact: true })).toBeVisible();
  await expect(page.locator("[data-price-changes]")).toHaveCount(0);
});

test("the list tags each change, jumps to its cell and badges the cell", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await withChanges(page, LIST);
  await page.goto("/pricing");
  const banner = page.locator('details[data-price-changes="list"]');
  await expect(banner.locator("summary")).toContainText("대비 변경 3건");
  await banner.locator("summary").click();
  await expect(banner.locator("[data-change-tag]")).toHaveText(["적용", "검토 대기", "제외 채널"]);
  await expect(banner.getByText("Claude Gone, AWS Bedrock - Global CRIS", { exact: true })).toBeVisible();
  await expect(banner.getByRole("button", { name: /Claude Gone/ })).toHaveCount(0);

  const cell = page.locator("#price-claude-opus-5-5-us");
  await expect(cell.locator('[data-badge="changed"]')).toHaveText("이전 대비 변경");
  await expect(cell.locator('[data-badge-detail="changed"]')).toHaveText("캐시 읽기 $0.44 → $0.22");
  await expect(page.locator("#price-gpt-6-astra-global [data-badge-detail=\"changed\"]")).toHaveText("검토 대기: 입력 — → $11.00");
  await expect(cell).toHaveAttribute("data-highlighted", "false");
  await banner.getByRole("button", { name: "Claude Opus 5.5, AWS Bedrock - US CRIS, 캐시 읽기 $0.44 → $0.22" }).click();
  await expect(cell).toHaveAttribute("data-highlighted", "true");
  await expect(cell).toBeInViewport();
  await expect(cell).toHaveAttribute("data-highlighted", "false", { timeout: 3000 });  // 1.5 s highlight
});

test("the banner fits a 390px phone without horizontal page scroll", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await withChanges(page, LIST);
  await page.goto("/pricing");
  await page.locator('details[data-price-changes="list"] summary').click();
  await expect(page.locator('details[data-price-changes="list"] li')).toHaveCount(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});
