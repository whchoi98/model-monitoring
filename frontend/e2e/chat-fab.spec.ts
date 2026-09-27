import { expect, test, type Locator, type Page } from "@playwright/test";
import { mockApi } from "./fixtures";

// The floating chat button (v2.31.1, user decision "스크롤 시 숨김"): it hides while the window scrolls down or a
// price table scrolls sideways, so it never covers table text (reported on /pricing at 390px), and comes back on a
// scroll up, at the page top or bottom, and on keyboard focus. The rule is src/lib/fabVisibility.ts (vitest).

type Box = { top: number; bottom: number; left: number; right: number };

const intersects = (a: Box, b: Box) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

function rect(locator: Locator): Promise<Box> {
  return locator.evaluate((element) => {
    const { top, bottom, left, right } = element.getBoundingClientRect();
    return { top, bottom, left, right };
  });
}

async function scrollWindowTo(page: Page, y: number) {
  await page.evaluate((top) => window.scrollTo(0, top), y);
  await expect.poll(() => page.evaluate(() => Math.round(window.scrollY))).toBe(y);
}

/** Faded out and slid below the viewport, so it covers nothing; hit testing passes through (pointer-events: none). */
async function expectHidden(button: Locator) {
  await expect(button).toHaveAttribute("data-visible", "false");
  await expect.poll(() => button.evaluate((element) => getComputedStyle(element).opacity)).toBe("0");
  await expect.poll(() => button.evaluate((element) => element.getBoundingClientRect().top >= window.innerHeight)).toBe(true);
  expect(await button.evaluate((element) => getComputedStyle(element).pointerEvents)).toBe("none");
}

async function expectShown(button: Locator) {
  await expect(button).toHaveAttribute("data-visible", "true");
  await expect.poll(() => button.evaluate((element) => getComputedStyle(element).opacity)).toBe("1");
  await expect(button).toBeInViewport({ ratio: 1 });
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("on a 390px phone the chat button hides while scrolling down or sideways and comes back up, at the bottom and on focus", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/pricing");
  await expect(page.locator('tr[data-family="gpt-5.4"]')).toBeVisible();
  const button = page.getByRole("button", { name: "챗봇 열기", exact: true });
  await expect(button).toBeEnabled();
  await expectShown(button);
  // 48px, 16px from the right and bottom edges below the sm breakpoint.
  const box = (await button.boundingBox())!;
  expect([box.width, box.height]).toEqual([48, 48]);
  expect(390 - (box.x + box.width)).toBe(16);
  expect(844 - (box.y + box.height)).toBe(16);
  const center = { x: box.x + box.width / 2, y: box.y + box.height / 2 };

  // Scroll down until the middle of the OpenAI table sits where the button was: the button is gone and the table text
  // under its former center is what a tap reaches.
  const table = page.getByRole("region", { name: "OpenAI 단가 표" });
  const target = await table.evaluate((element, y) => {
    const box = element.getBoundingClientRect();
    return Math.round(window.scrollY + box.top + box.height / 2 - y);
  }, center.y);
  expect(target).toBeGreaterThan(100);
  await scrollWindowTo(page, target);
  await expectHidden(button);
  const under = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.closest("[data-pricing-scroll]")?.getAttribute("aria-label") ?? null, center);
  expect(under).toBe("OpenAI 단가 표");

  // Scrolling back up shows it again.
  await scrollWindowTo(page, target - 200);
  await expectShown(button);

  // Scrolling a price table sideways hides it; the window does not move.
  await table.evaluate((element) => { element.scrollLeft = 200; });
  await expectHidden(button);
  expect(await page.evaluate(() => Math.round(window.scrollY))).toBe(target - 200);

  // Keyboard: Tab from the last reference link reaches the hidden button (still in the tab order) and shows it,
  // without scrolling the page.
  await page.evaluate(() => {
    const links = document.querySelectorAll<HTMLAnchorElement>('section[aria-labelledby="pricing-references-title"] a');
    links[links.length - 1].focus({ preventScroll: true });
  });
  await expect(button).toHaveAttribute("data-visible", "false");
  await page.keyboard.press("Tab");
  await expect(button).toBeFocused();
  await expectShown(button);
  expect(await page.evaluate(() => Math.round(window.scrollY))).toBe(target - 200);
  expect(await button.getAttribute("aria-hidden")).toBeNull();
  expect(await button.getAttribute("tabindex")).toBeNull();
  // Leaving it does not make it vanish: focus showed it, and only the next scroll down or sideways hides it.
  await button.evaluate((element) => (element as HTMLButtonElement).blur());
  await expect(button).not.toBeFocused();
  await expect(button).toHaveAttribute("data-visible", "true");

  // Hidden again by a sideways scroll, then the page bottom shows it, clear of the last content block.
  await table.evaluate((element) => { element.scrollLeft = 0; });
  await expectHidden(button);
  const bottom = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
  await scrollWindowTo(page, bottom);
  await expectShown(button);
  const references = page.locator('section[aria-labelledby="pricing-references-title"]');
  const fab = await rect(button);
  const last = await rect(references);
  expect(intersects(fab, last)).toBe(false);
  expect(last.bottom).toBeLessThanOrEqual(fab.top);
});

test("at 1440px the visible chat button stays clear of the price tables at the page end", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/pricing");
  await expect(page.locator('tr[data-family="gpt-5.4"]')).toBeVisible();
  const button = page.getByRole("button", { name: "챗봇 열기", exact: true });
  await expectShown(button);
  // 64px, 24px from the right and bottom edges from the sm breakpoint.
  const box = (await button.boundingBox())!;
  expect([box.width, box.height]).toEqual([64, 64]);
  expect(1440 - (box.x + box.width)).toBe(24);
  expect(900 - (box.y + box.height)).toBe(24);

  const bottom = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
  expect(bottom).toBeGreaterThan(0);
  await scrollWindowTo(page, bottom);
  await expectShown(button);
  const fab = await rect(button);
  const tables = page.locator("main [data-pricing-scroll]");
  await expect(tables).toHaveCount(3);
  for (const table of await tables.all()) {
    const box = await rect(table);
    expect(box.right).toBeLessThanOrEqual(fab.left);
    expect(intersects(fab, box)).toBe(false);
  }
  for (const section of await page.locator("main section").all()) {
    expect(intersects(fab, await rect(section))).toBe(false);
  }
});
