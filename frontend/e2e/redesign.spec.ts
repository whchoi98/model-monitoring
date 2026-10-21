import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem("lang", "en"));
});

test("quick navigation searches pages and preserves keyboard focus", async ({ page }) => {
  await page.goto("/cost");
  const trigger = page.getByRole("button", { name: "Quick navigation", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("searchbox").fill("pricing");
  await dialog.getByRole("link", { name: /Unit Prices/ }).click();
  await expect(page).toHaveURL(/\/pricing$/);
  await expect(page.getByRole("heading", { name: "Unit Prices", exact: true })).toBeVisible();
  await expect(dialog).toHaveCount(0);
  await trigger.click();
  await dialog.getByRole("searchbox").fill("no-page-with-this-name");
  await expect(dialog.getByRole("status")).toHaveText("No matching pages.");
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
});

test("page search shortcut does not interrupt another modal or IME input", async ({ page }) => {
  await page.goto("/cost");
  await expect(page.getByRole("button", { name: "Quick navigation", exact: true })).toBeVisible();
  await page.evaluate(() => document.dispatchEvent(new KeyboardEvent("keydown", {
    key: "k", ctrlKey: true, isComposing: true, bubbles: true,
  })));
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog").getByRole("searchbox")).toBeFocused();
  await page.keyboard.press("Escape");
  await page.locator("header").getByRole("button", { name: "Login", exact: true }).click();
  await page.keyboard.press("Control+k");
  await expect(page.getByRole("dialog")).toHaveCount(1);
  await expect(page.getByRole("dialog").getByRole("searchbox")).toHaveCount(0);
});

test("new visitors get light controls and their chosen theme survives reload", async ({ page }) => {
  await page.goto("/cost");
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("light");
  await page.getByRole("button", { name: "Switch to dark theme", exact: true }).click();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("dark");
  await page.reload();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("dark");
  await page.getByRole("button", { name: "Switch to light theme", exact: true }).click();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("light");
});

test("theme changes reach another tab without reloading", async ({ page, context }) => {
  await page.goto("/cost");
  const second = await context.newPage();
  await mockApi(second);
  await second.goto("/pricing");
  await page.getByRole("button", { name: "Switch to dark theme", exact: true }).click();
  await expect.poll(() => second.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("dark");
  await expect.poll(() => second.locator('meta[name="theme-color"]').getAttribute("content")).toBe("#101827");
});


test("mobile chat stays inside the screen and restores focus", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "Safari uses the separately tested popup chat.");
  await page.setViewportSize({ width: 320, height: 740 });
  await page.addInitScript(() => localStorage.setItem("auth_token", "redesign-chat-token"));
  await page.route("**/api/auth/me", route => route.fulfill({ json: { id: 1, username: "chat-user" } }));
  await page.goto("/cost");
  const trigger = page.getByRole("button", { name: "Open chatbot", exact: true });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "AI assistant", exact: true });
  await expect(dialog).toBeVisible();
  const box = await dialog.boundingBox();
  expect(box).not.toBeNull();
  expect(box!.x).toBeGreaterThanOrEqual(8);
  expect(box!.y).toBeGreaterThanOrEqual(8);
  expect(box!.x + box!.width).toBeLessThanOrEqual(312);
  expect(box!.y + box!.height).toBeLessThanOrEqual(732);
  await expect(dialog.getByRole("textbox", { name: "Message", exact: true })).toBeFocused();
  for (let i = 0; i < 10; i++) {
    await page.keyboard.press("Tab");
    expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});


test("theme still works across navigation when storage writes fail", async ({ page }) => {
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === "theme") throw new DOMException("Storage blocked", "SecurityError");
      original.call(this, key, value);
    };
  });
  await page.goto("/cost");
  await page.getByRole("button", { name: "Switch to dark theme", exact: true }).click();
  await page.locator("header").getByRole("link", { name: "Unit Prices", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Unit Prices", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("dark");
  await page.getByRole("button", { name: "Switch to light theme", exact: true }).click();
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("light");
});


test("an unavailable insight is distinct from an empty result and can be retried", async ({ page }) => {
  let unavailable = true;
  await page.route("**/api/insights/latest", route => route.fulfill(unavailable
    ? { status: 503, json: { detail: "Temporarily unavailable" } }
    : { json: null }));
  await page.goto("/");
  const panel = page.getByRole("region", { name: "AI Insights", exact: true });
  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(panel.getByText(/No insight yet/)).toHaveCount(0);
  unavailable = false;
  await panel.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(panel.getByText(/No insight yet/)).toBeVisible();
});
