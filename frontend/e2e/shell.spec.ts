import { expect, test } from "@playwright/test";
import { mockApi, modelCatalog } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem("lang", "en"));
});

test("HTML stays uncached while versioned assets and PWA resources remain available", async ({ request }) => {
  const page = await request.get("/");
  expect(page.ok()).toBe(true);
  expect(page.headers()["cache-control"]).toContain("no-store");
  const html = await page.text();
  expect(html).toContain("viewport-fit=cover");
  const asset = html.match(/(?:src|href)="([^"]*\/_next\/static\/[^"]+\.(?:js|css)(?:\?[^"]*)?)"/)?.[1];
  expect(asset).toBeDefined();
  const script = await request.get(asset!);
  expect(script.ok()).toBe(true);
  expect(script.headers()["cache-control"]).toContain("immutable");
  const manifest = await request.get("/manifest.webmanifest");
  expect(manifest.ok()).toBe(true);
  const pwa = await manifest.json();
  expect(pwa.display).toBe("standalone");
  expect(pwa.icons.length).toBeGreaterThan(0);
  expect((await request.get(pwa.icons[0].src)).ok()).toBe(true);
});

for (const width of [390, 1024, 1280, 1440]) {
  test(`navigation fits at ${width}px in both languages`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/cost");
    await expect(page.locator("header")).toBeVisible();
    for (const language of ["ko", "en"]) {
      if (width < 768) {
        await page.locator("header button[aria-controls]").click();
      }
      await page.locator(`header button[lang="${language}"]:visible`).click();
      await expect(page.locator("html")).toHaveAttribute("lang", language);
      await expect.poll(() => page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      )).toBe(true);
      await expect(page.locator("header").getByRole("link", { name: "LLM Monitor", exact: true })).toBeVisible();
      if (width < 768) {
        await page.keyboard.press("Escape");
        await expect(page.locator("header button[aria-controls]")).toHaveAttribute("aria-expanded", "false");
        await expect(page.locator("header button[aria-controls]")).toBeFocused();
      }
    }
  });
}

test("public content renders while the authentication request is pending", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("auth_token", "shell-token"));
  let release!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/auth/me", async (route) => {
    await pending;
    await route.fulfill({ json: { id: 1, username: "shell-user" } });
  });
  try {
    await page.goto("/cost");
    await expect(page.locator("header")).toBeVisible({ timeout: 2000 });
    await expect(page.getByRole("heading", { name: "Cost Dashboard", exact: true })).toBeVisible();
  } finally {
    release();
  }
});

test("a temporary authentication failure preserves the token and can be retried", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("auth_token", "shell-token"));
  let unavailable = true;
  await page.route("**/api/auth/me", (route) => route.fulfill(unavailable
    ? { status: 503, json: { detail: "Temporarily unavailable" } }
    : { json: { id: 1, username: "shell-user" } }));
  await page.goto("/cost");
  await expect(page.getByRole("heading", { name: "Cost Dashboard", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("auth_token"))).toBe("shell-token");
  const retry = page.getByRole("button", { name: "Retry sign-in check" });
  await expect(retry).toBeVisible();
  unavailable = false;
  await retry.click();
  await expect(page.locator("header").getByText("shell-user", { exact: true })).toBeVisible();
});

for (const status of [401, 403]) {
  test(`a verified ${status} clears an invalid session`, async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("auth_token", "shell-token"));
    await page.route("**/api/auth/me", (route) => route.fulfill({
      status, json: { detail: "Invalid session" },
    }));
    await page.goto("/cost");
    await expect.poll(() => page.evaluate(() => localStorage.getItem("auth_token"))).toBeNull();
    await expect(page.locator("header").getByRole("button", { name: "Login", exact: true })).toBeEnabled();
  });
}

test("navigation retains the verified user without checking auth again", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("auth_token", "shell-token"));
  let checks = 0;
  await page.route("**/api/auth/me", (route) => {
    checks += 1;
    return route.fulfill({ json: { id: 1, username: "shell-user" } });
  });
  await page.goto("/cost");
  await expect(page.locator("header").getByText("shell-user", { exact: true })).toBeVisible();
  const initialChecks = checks;
  await page.locator("header").getByRole("link", { name: "Reliability", exact: true }).click();
  await expect(page).toHaveURL(/\/reliability$/);
  await expect(page.getByRole("heading", { name: "Multi-channel Reliability", exact: true })).toBeVisible();
  await expect(page.locator("header").getByText("shell-user", { exact: true })).toBeVisible();
  expect(checks).toBe(initialChecks);
});

test("browser tab titles follow the active page and language", async ({ page, context }) => {
  await page.goto("/cost");
  await expect(page).toHaveTitle("Cost | LLM Monitor");
  await page.locator("header").getByRole("link", { name: "Reliability", exact: true }).click();
  await expect(page).toHaveTitle("Reliability | LLM Monitor");
  await page.locator("header button[lang='ko']:visible").click();
  await expect(page).toHaveTitle("신뢰성 | LLM Monitor");

  const chat = await context.newPage();
  await mockApi(chat);
  await chat.goto("/chat");
  await expect(chat).toHaveTitle("챗봇 | LLM Monitor");
});

test("Manual Probe follows the URL across navigation, reload, and Back", async ({ page }) => {
  await page.goto("/cost");
  await page.locator("header").getByRole("link", { name: "Manual Probe", exact: true }).click();
  await expect(page).toHaveURL(/view=manual/);
  const manualHeading = page.getByRole("main").getByRole("heading", { name: "Manual Probe", exact: true });
  await expect(manualHeading).toBeVisible();
  await expect(page.locator("header a[aria-current='page']:visible")).toHaveText("Manual Probe");
  await page.reload();
  await expect(manualHeading).toBeVisible();
  await page.locator("header").getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page).not.toHaveURL(/view=manual/);
  await page.goBack();
  await expect(page).toHaveURL(/view=manual/);
  await expect(manualHeading).toBeVisible();
});

test("the shared login dialog traps focus and returns it on Escape", async ({ page }) => {
  await page.goto("/cost");
  const login = page.locator("header").getByRole("button", { name: "Login", exact: true });
  await login.click();
  const dialog = page.getByRole("dialog", { name: "Login", exact: true });
  await expect(dialog).toBeVisible();
  for (let i = 0; i < 10; i += 1) {
    await page.keyboard.press("Tab");
    await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  }
  await dialog.getByRole("button", { name: "Close login" }).focus();
  await page.keyboard.press("Shift+Tab");
  await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(login).toBeFocused();
});

test("shared login keeps the manual probe configuration usable across tab navigation", async ({ page }) => {
  await page.route("**/api/auth/login", (route) => route.fulfill({
    json: { access_token: "shell-token", username: "shell-user" },
  }));
  await page.route("**/api/auth/me", (route) => route.fulfill({
    json: { id: 1, username: "shell-user" },
  }));
  await page.goto("/?view=manual");
  await page.locator("header").getByRole("button", { name: "Login", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Login", exact: true });
  await dialog.getByPlaceholder("admin").fill("shell-user");
  await dialog.locator('input[type="password"]').fill("shell-password");
  await dialog.getByRole("button", { name: "Login", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(page.locator("header").getByText("shell-user", { exact: true })).toBeVisible();
  await expect(page.getByRole("main")).toHaveCount(1);
  await expect(page.locator("main main")).toHaveCount(0);
  await expect.poll(() => page.getByRole("complementary").evaluate((sidebar) => {
    const headerHeight = document.querySelector("header")!.getBoundingClientRect().height;
    const sidebarTop = Number.parseFloat(getComputedStyle(sidebar).top);
    return Math.abs(sidebarTop - headerHeight) < 1;
  })).toBe(true);
  const model = page.getByRole("checkbox", { name: modelCatalog[0].name, exact: true });
  await model.press("Space");
  const prompt = page.getByPlaceholder("Enter your test prompt...");
  await prompt.fill("Shell regression prompt");
  await page.locator("header").getByRole("link", { name: "Dashboard", exact: true }).click();
  await expect(page).not.toHaveURL(/view=manual/);
  await page.locator("header").getByRole("link", { name: "Manual Probe", exact: true }).click();
  await expect(prompt).toHaveValue("Shell regression prompt");
  await expect(model).toBeChecked();
});

test("signing out updates another open tab", async ({ page, context }) => {
  await page.addInitScript(() => localStorage.setItem("auth_token", "shell-token"));
  await page.route("**/api/auth/me", (route) => route.fulfill({ json: { id: 1, username: "shell-user" } }));
  await page.goto("/cost");
  await expect(page.locator("header").getByText("shell-user", { exact: true })).toBeVisible();
  const other = await context.newPage();
  await mockApi(other);
  await other.route("**/api/auth/me", (route) => route.fulfill({ json: { id: 1, username: "shell-user" } }));
  await other.goto("/reliability");
  await expect(other.locator("header").getByText("shell-user", { exact: true })).toBeVisible();
  await page.locator("header").getByRole("button", { name: "Logout", exact: true }).click();
  await expect(other.locator("header").getByRole("button", { name: "Login", exact: true })).toBeEnabled();
  await expect(other.locator("header").getByText("shell-user", { exact: true })).toHaveCount(0);
});

test("language remains usable when localStorage throws", async ({ page }) => {
  await page.addInitScript(() => {
    Storage.prototype.getItem = () => { throw new DOMException("Storage blocked", "SecurityError"); };
    Storage.prototype.setItem = () => { throw new DOMException("Storage blocked", "SecurityError"); };
  });
  await page.goto("/cost");
  await page.locator("header button[lang='en']:visible").click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await page.locator("header").getByRole("link", { name: "Reliability", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Multi-channel Reliability", exact: true })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
});

test("the chat popup receives the saved language", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("auth_token", "shell-token"));
  await page.route("**/api/auth/me", (route) => route.fulfill({ json: { id: 1, username: "shell-user" } }));
  await page.goto("/chat");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page).toHaveTitle("Chat | LLM Monitor");
  await expect(page.getByRole("button", { name: /Which model is most cost-efficient this week\?/ })).toBeVisible();
});
