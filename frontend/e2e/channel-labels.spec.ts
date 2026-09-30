import { expect, test, type Locator, type Page } from "@playwright/test";
import type { ChannelCompare, CostSummary } from "../src/lib/api";
import { mockApi, monitoringData } from "./fixtures";

// v2.32.0 서울 In-Region 채널 라벨 — 390px에서 리전 코드가 하이픈에서 끊기지 않는다("(ap-" / "northeast-2)"이던 회귀).
const SEOUL = { id: "bedrock:ap-northeast-2:anthropic.claude-opus-5", name: "Bedrock Claude Opus 5 (ap-northeast-2)" };
const CHANNEL = "Bedrock ap-northeast-2";

/** Vertical spread (px) of the line boxes that render `needle` inside `scope`: near 0 when it sits on one line. */
async function lineSpread(scope: Locator, needle: string): Promise<number> {
  return scope.evaluate((root, text) => {
    const nodes: Text[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) nodes.push(node as Text);
    const start = nodes.map((node) => node.data).join("").indexOf(text);
    if (start < 0) throw new Error(`"${text}" is not rendered`);
    const end = start + text.length;
    const range = document.createRange();
    let offset = 0;
    for (const node of nodes) {
      const next = offset + node.data.length;
      if (start >= offset && start < next) range.setStart(node, start - offset);
      if (end > offset && end <= next) range.setEnd(node, end - offset);
      offset = next;
    }
    const tops = [...range.getClientRects()].filter((rect) => rect.width > 0).map((rect) => rect.top);
    return Math.max(...tops) - Math.min(...tops);
  }, needle);
}

async function mockSeoul(page: Page) {
  await mockApi(page);
  const [base] = monitoringData().latest;
  await page.route("**/api/models", (route) => route.fulfill({ json: [SEOUL] }));
  await page.route("**/api/auto-probe/latest*", (route) => route.fulfill({
    json: [{ ...base, model_id: SEOUL.id, model_name: SEOUL.name }],
  }));
  await page.setViewportSize({ width: 390, height: 844 });
}

test("at 390px the dashboard card keeps the Seoul region code on one line", async ({ page }) => {
  await mockSeoul(page);
  await page.goto("/");
  const card = page.getByRole("region", { name: "모델별 최신 상태" }).getByRole("article").filter({ hasText: SEOUL.name });
  await expect(card).toHaveCount(1);
  expect(await lineSpread(card, "(ap-northeast-2)")).toBeLessThan(4);
});

test("at 390px the Model Explorer card and dialog title keep the Seoul region code on one line", async ({ page }) => {
  await mockSeoul(page);
  await page.goto("/models");
  const card = page.getByRole("button", { name: SEOUL.name, exact: true });
  await expect(card).toBeVisible();
  expect(await lineSpread(card.getByRole("heading"), "(ap-northeast-2)")).toBeLessThan(4);
  await card.click();
  const title = page.getByRole("dialog", { name: SEOUL.name }).getByRole("heading", { level: 2 });
  await expect(title).toHaveText(SEOUL.name);
  expect(await lineSpread(title, "(ap-northeast-2)")).toBeLessThan(4);
});

test("at 390px the cost table keeps the Seoul region code and the channel badge on one line", async ({ page }) => {
  await mockSeoul(page);
  const summary: CostSummary = {
    window: "24h", since: "2026-09-29T00:00:00Z", total_cost_usd: 1.2, total_input_tokens: 1200, total_output_tokens: 2400,
    rows: [{
      model_id: SEOUL.id, model_name: SEOUL.name, channel: CHANNEL, samples: 12,
      input_tokens: 1200, output_tokens: 2400, cost_usd: 1.2, avg_cost_per_call_usd: 0.1,
    }],
  };
  const channels: ChannelCompare = {
    window: "24h", since: summary.since,
    channels: [{ channel: CHANNEL, samples: 12, input_tokens: 1200, output_tokens: 2400, cost_usd: 1.2 }],
  };
  await page.route("**/api/cost/summary?*", (route) => route.fulfill({ json: summary }));
  await page.route("**/api/cost/channel-compare?*", (route) => route.fulfill({ json: channels }));
  await page.goto("/cost");
  const name = page.locator("table").getByRole("cell", { name: SEOUL.name, exact: true });
  await expect(name).toBeVisible();
  expect(await lineSpread(name, "(ap-northeast-2)")).toBeLessThan(4);
  const badge = page.locator("table").getByText(CHANNEL, { exact: true });
  await expect(badge).toBeVisible();
  expect(await lineSpread(badge, CHANNEL)).toBeLessThan(4);
});
