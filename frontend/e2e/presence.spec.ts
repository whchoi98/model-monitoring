import { expect, test, type Page, type Route } from "@playwright/test";
import { mockApi } from "./fixtures";
import { presenceHttpFixture } from "./presence-http";

function response(total = 10007, active = 2, now = new Date().toISOString()) {
  return { active_visitors: active, total_visitors: total, initial_total: 10000,
    window_seconds: 90, as_of: now, counting_since: "2026-10-21T00:00:00Z" };
}

async function fixture(page: Page, handler: (route: Route) => Promise<void>) {
  // The isolated browser container has no network interface; these API fixtures
  // simulate a reachable service, including the browser's online signal.
  await page.addInitScript(() => Object.defineProperty(navigator, "onLine", { configurable: true, value: true }));
  await mockApi(page);
  await page.route("**/api/presence", handler);
}

test("footer displays server counts and keeps the same session across page navigation", async ({ page }) => {
  const methods: string[] = [];
  await fixture(page, async (route) => {
    methods.push(route.request().method());
    await route.fulfill({
      json: response(),
      headers: { "cache-control": "no-store", "set-cookie": "llm_monitor_visitor=fixture; Path=/api/presence; HttpOnly; SameSite=Lax" },
    });
  });
  await page.goto("/");
  const footer = page.getByRole("contentinfo", { name: "접속 통계", exact: true });
  await expect(footer.getByRole("definition").nth(0)).toHaveText("2");
  await expect(footer.getByRole("definition").nth(1)).toHaveText("10,007");
  await expect.poll(() => methods.slice(0, 2)).toEqual(["GET", "POST"]);
  await footer.getByText("집계 기준", { exact: true }).click();
  await expect(footer).toContainText("10,000");
  await page.getByRole("navigation", { name: "주요 메뉴" }).getByRole("link", { name: "비용 단가", exact: true }).click();
  await expect(page).toHaveURL(/\/pricing$/);
  await expect(footer.getByRole("definition").nth(1)).toHaveText("10,007");
  expect(methods.filter((method) => method === "GET")).toHaveLength(1);
});

test("footer does not fabricate zero or 10000 when counting is unavailable", async ({ page }) => {
  await fixture(page, async (route) => { await route.fulfill({ status: 503, json: { detail: "Unavailable" } }); });
  await page.goto("/");
  const footer = page.getByRole("contentinfo", { name: "접속 통계", exact: true });
  await expect(footer).toContainText("집계 확인 불가");
  await expect(footer.getByRole("definition").nth(0)).toHaveText("—");
  await expect(footer.getByRole("definition").nth(1)).toHaveText("—");
});

test("hidden pages stop heartbeats and resume without presenting old activity as current", async ({ page }) => {
  await page.clock.install({ time: new Date() });
  let posts = 0;
  await fixture(page, async (route) => {
    if (route.request().method() === "POST") posts++;
    await route.fulfill({ json: response(10001, 1, await page.evaluate(() => new Date().toISOString())) });
  });
  await page.goto("/");
  const footer = page.getByRole("contentinfo", { name: "접속 통계", exact: true });
  await expect(page.getByRole("region", { name: "모델별 최신 상태", exact: true })).toBeVisible();
  await page.clock.fastForward(1);
  await expect(footer.getByRole("definition").nth(0)).toHaveText("1");
  await expect.poll(() => posts).toBeGreaterThan(0);
  const before = posts;
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.fastForward(60000);
  expect(posts).toBe(before);
  await expect(footer.getByRole("definition").nth(0)).toHaveText("—");
  await expect(footer.getByRole("definition").nth(1)).toHaveText("10,001");
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, value: false });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.fastForward(5001);
  await expect.poll(() => posts).toBeGreaterThan(before);
  await expect(footer.getByRole("definition").nth(0)).toHaveText("1");
});

test("simultaneous tabs and reloads share one signed cookie over real HTTP", async ({ context, page, baseURL }) => {
  const other = await context.newPage();
  const http = await presenceHttpFixture(baseURL!);
  try {
    for (const tab of [page, other]) {
      await fixture(tab, (route) => route.continue());
    }
    await Promise.all([page.goto(`${http.origin}/`), other.goto(`${http.origin}/pricing`)]);
    for (const tab of [page, other]) {
      await expect(tab.getByRole("contentinfo", { name: "접속 통계", exact: true }).getByRole("definition").nth(1)).toHaveText("10,001");
    }
    await Promise.all([page.reload(), other.reload()]);
    for (const tab of [page, other]) {
      await expect(tab.getByRole("contentinfo", { name: "접속 통계", exact: true }).getByRole("definition").nth(1)).toHaveText("10,001");
    }
    expect(http.bootstraps()).toBe(1);
    expect(http.seen.size).toBe(1);
    await expect.poll(() => http.posts.length).toBeGreaterThanOrEqual(4);
    expect(new Set(http.posts).size).toBe(1);
    const cookie = (await context.cookies()).find((item) => item.name === "llm_monitor_visitor");
    expect(cookie).toMatchObject({ httpOnly: true, sameSite: "Lax", path: "/api/presence" });
  } finally {
    await other.close();
    await http.close();
  }
});
