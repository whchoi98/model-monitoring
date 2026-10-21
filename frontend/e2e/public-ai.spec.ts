import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => { localStorage.setItem("lang", "en"); localStorage.removeItem("auth_token"); });
});

test("a visitor can chat, continue the conversation and start over without signing in", async ({ page }) => {
  const requests: { message: string; session_id?: string | null }[] = [];
  await page.route("**/api/chat/stream", async route => {
    expect(route.request().headers()["authorization"]).toBeUndefined();
    requests.push(route.request().postDataJSON());
    await route.fulfill({ contentType: "text/event-stream", body: 'event: delta\ndata: {"text":"The monitored channels are healthy."}\n\nevent: final\ndata: {"ok":true,"session_id":"chat-public-browser"}\n\n' });
  });
  await page.goto("/chat");
  await expect(page.getByText("Haiku 5.5", { exact: true })).toBeVisible();
  const input = page.getByRole("textbox", { name: "Message", exact: true });
  await input.fill("Which model is fastest?");
  await input.press("Enter");
  await expect(page.getByText("The monitored channels are healthy.", { exact: true })).toBeVisible();
  await input.fill("What about errors?");
  await input.press("Enter");
  await expect.poll(() => requests.length).toBe(2);
  expect(requests[1].session_id).toBe("chat-public-browser");
  await page.getByRole("button", { name: "New chat", exact: true }).click();
  await input.fill("Start again");
  await input.press("Enter");
  await expect.poll(() => requests.length).toBe(3);
  expect(requests[2].session_id).toBeNull();
  await expect(page.getByRole("dialog", { name: "Login", exact: true })).toHaveCount(0);
});

test("public insight reading opens a movable window, maximizes and restores focus", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  let reads = 0;
  await page.route("**/api/insights/latest", route => {
    reads++;
    return route.fulfill({ json: {
      id: reads, created_at: "2026-10-21T12:00:00Z",
      window_start: "2026-10-21T06:00:00Z", window_end: "2026-10-21T12:00:00Z",
      summary_md: "## 분석\n\n전체 결과입니다.", summary_md_en: "## Monitoring summary\n\n" + "A detailed monitoring observation. ".repeat(30) + "\n\n## Final recommendation\n\nCompare channels for the same workload.",
      model_breakdown: {},
    } });
  });
  await page.goto("/");
  const panel = page.getByRole("region", { name: "AI Insights", exact: true });
  await expect(panel.getByText("HAIKU 5.5", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: /sign in|login/i })).toHaveCount(0);
  const before = reads;
  await panel.getByRole("button", { name: "Refresh AI insights", exact: true }).click();
  await expect.poll(() => reads).toBeGreaterThan(before);
  const trigger = panel.getByRole("button", { name: "Read full analysis", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "AI Insights", exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("heading", { name: "Final recommendation" })).toBeAttached();
  const original = (await dialog.boundingBox())!;
  await dialog.getByRole("button", { name: "Full screen", exact: true }).click();
  await expect(dialog).toHaveAttribute("data-maximized", "true");
  const full = (await dialog.boundingBox())!;
  expect(full.width).toBeGreaterThan(original.width + 100);
  expect(full.width).toBeLessThanOrEqual(1440);
  await dialog.getByRole("button", { name: "Restore size", exact: true }).click();
  await expect(dialog).toHaveAttribute("data-maximized", "false");
  const handle = dialog.locator("[data-window-drag]");
  const bounds = (await handle.boundingBox())!;
  await page.mouse.move(bounds.x + 90, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + 145, bounds.y + bounds.height / 2 + 35, { steps: 4 });
  await page.mouse.up();
  expect((await dialog.boundingBox())!.x).toBeGreaterThan(original.x + 30);
  for (let i = 0; i < 7; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("an anonymous visitor opens the floating chatbot immediately", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "Safari's popup entry is covered by the public chat page.");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/cost");
  const trigger = page.getByRole("button", { name: "Open chatbot", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "AI assistant", exact: true });
  await expect(dialog.getByRole("textbox", { name: "Message", exact: true })).toBeFocused();
  await expect(page.getByRole("dialog", { name: "Login", exact: true })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});

for (const width of [1024, 1440, 1920]) {
  test(`navigation shares the content edges and exposes every destination at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 960 });
    await page.goto("/pricing");
    for (const language of ["ko", "en"]) {
      await page.locator(`header button[lang="${language}"]:visible`).click();
      const links = page.getByRole("navigation", { name: language === "en" ? "Primary navigation" : "주요 메뉴", exact: true }).getByRole("link");
      await expect(links).toHaveCount(12);
      for (const link of await links.all()) await expect(link).toBeInViewport();
      const edges = await page.evaluate(() => {
        const main = document.querySelector("main")!;
        const box = main.getBoundingClientRect();
        const style = getComputedStyle(main);
        const nav = [...document.querySelectorAll(".primary-navigation a")].map(el => el.getBoundingClientRect());
        const brand = document.querySelector(".app-header-top > a")!.getBoundingClientRect();
        return { left: box.left + parseFloat(style.paddingLeft), right: box.right - parseFloat(style.paddingRight),
          navLeft: Math.min(...nav.map(box => box.left)), navRight: Math.max(...nav.map(box => box.right)),
          brandLeft: brand.left, overflow: document.documentElement.scrollWidth > innerWidth };
      });
      expect(Math.abs(edges.left - edges.navLeft)).toBeLessThan(2);
      expect(Math.abs(edges.right - edges.navRight)).toBeLessThan(2);
      expect(Math.abs(edges.left - edges.brandLeft)).toBeLessThan(2);
      expect(edges.overflow).toBe(false);
    }
  });
}

for (const width of [768, 820, 1024]) {
  test(`signed-in tablet controls do not overlap the logo at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 960 });
    await page.addInitScript(() => localStorage.setItem("auth_token", "tablet-session"));
    await page.route("**/api/auth/me", route => route.fulfill({ json: { id: 1, username: "very-long-monitoring-member@example.com" } }));
    await page.goto("/");
    await expect(page.locator("header").getByRole("button", { name: "Logout", exact: true })).toBeVisible();
    const layout = await page.evaluate(() => {
      const top = document.querySelector(".app-header-top")!;
      const brand = top.querySelector("a")!.getBoundingClientRect();
      const title = top.querySelector("a > span:nth-child(2)")!.getBoundingClientRect();
      const controls = top.lastElementChild!.getBoundingClientRect();
      return { labelRight: Math.max(brand.right, title.right), controlsLeft: controls.left, controlsRight: controls.right, width: innerWidth };
    });
    expect(layout.controlsLeft - layout.labelRight).toBeGreaterThanOrEqual(8);
    expect(layout.controlsRight).toBeLessThanOrEqual(layout.width - 16);
  });
}
