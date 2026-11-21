import { expect, test, type Page } from "@playwright/test";
import { mockApi } from "./fixtures";

const feature = {
  id: "tool_use", group: "core", label_ko: "도구 사용", label_en: "Tool use",
  desc_ko: "도구 실행 확인", desc_en: "Verify tool execution", doc_url: "",
  documented: { cp: "ga" }, verification: "evidence", notes: "",
};
const model = { key: "fable", label: "Claude Fable 5.1", cp: "fable", mantle: null, bedrock: "global.fable" };
const cell = {
  feature: "tool_use", surface: "cp", model_key: "fable", model_label: "Claude Fable 5.1", model_id: "global.fable",
  status: "broken", documented: "ga", verdict: "drift", latency_ms: 250,
};
const parityCell = { model_id: "global.fable", model_name: "Bedrock Claude Fable 5.1 (Global)", surface: "converse", feature: "tool_use", status: "broken", latency_ms: 250 };

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem("lang", "en"));
  const run = { id: 7, started_at: new Date().toISOString(), finished_at: new Date().toISOString(), totals: { broken: 1 }, running: false, catalog_version: "fixture" };
  await page.route("**/api/parity/catalog", (route) => route.fulfill({ json: { features: [feature], surfaces: ["converse"] } }));
  await page.route("**/api/parity/latest", (route) => route.fulfill({ json: { run, results: [parityCell], changes: [], previous_run_id: 6 } }));
  await page.route("**/api/features/catalog", (route) => route.fulfill({ json: {
    features: [feature], groups: [{ id: "core", label_ko: "코어", label_en: "Core" }],
    surfaces: [{ id: "cp", label: "Claude Platform", short: "CP", group: "cp", region: "us-east-2" }], models: [model],
  } }));
  await page.route("**/api/features/latest", (route) => route.fulfill({ json: { run, results: [cell], changes: [], drift: [cell], previous_run_id: 6 } }));
});

for (const [path, api, heading] of [["/parity", "parity", "Parity Run"], ["/claude-features", "features", "Claude API Features"]]) {
  test(`${path} reports a failed request and retries without claiming no runs exist`, async ({ page }) => {
    let failed = true;
    await page.route(`**/api/${api}/latest`, (route) => failed ? route.fulfill({ status: 503, json: { detail: "Unavailable" } }) : route.fallback());
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    const alert = page.getByRole("alert").filter({ hasText: "Could not load" });
    await expect(alert).toBeVisible();
    await expect(page.getByText(/No (parity|verification) run yet/)).toHaveCount(0);
    failed = false;
    await alert.getByRole("button", { name: "Retry", exact: true }).click();
    await expect(page.getByRole("table")).toBeVisible();
  });

  test(`${path} opens the shared sign-in dialog before a protected run`, async ({ page }) => {
    let triggered = false;
    await page.route(`**/api/${api}/trigger`, (route) => {
      triggered = true;
      return route.fulfill({ status: 401, json: { detail: "Unauthorized" } });
    });
    await page.goto(path);
    await page.getByRole("button", { name: api === "parity" ? "Run parity sweep" : "Run verification", exact: true }).click();
    await expect(page.getByRole("dialog", { name: "Login", exact: true })).toBeVisible();
    expect(triggered).toBe(false);
  });
}

test("parity evidence can be retried and Escape restores focus to the result", async ({ page }) => {
  let failed = true;
  await page.route("**/api/parity/evidence?*", (route) => failed
    ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
    : route.fulfill({ json: { ...parityCell, error_message: "Canary absent", evidence: { request: { prompt: "probe" }, signal: "missing" } } }));
  await page.goto("/parity");
  const result = page.getByRole("table").getByRole("button", { name: "Broken", exact: true });
  await result.click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("alert")).toBeVisible();
  failed = false;
  await dialog.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(dialog.getByText("Canary absent", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(result).toBeFocused();
});


// Both pages re-render once per second for the auto-refresh countdown. Waiting for the countdown to move
// ties the tests below to those re-renders instead of to an arbitrary delay.
async function countdownTicks(page: Page, ticks = 2) {
  const countdown = page.locator(".refresh-controls label .tabular-nums");
  const start = Number.parseInt(await countdown.innerText(), 10);
  await expect.poll(async () => start - Number.parseInt(await countdown.innerText(), 10), { timeout: 10_000 }).toBeGreaterThanOrEqual(ticks);
}

for (const [path, api] of [["/parity", "parity"], ["/claude-features", "features"]]) {
  test(`${path} supported evidence disclosures are reachable and openable with the keyboard`, async ({ page }) => {
    const supported = api === "parity" ? { ...parityCell, status: "supported" } : { ...cell, status: "supported", verdict: "match" };
    const run = { id: 8, started_at: new Date().toISOString(), finished_at: new Date().toISOString(), totals: { supported: 1 }, running: false, catalog_version: "fixture" };
    await page.route(`**/api/${api}/latest`, route => route.fulfill({ json: { run, results: [supported], changes: [], drift: [], previous_run_id: 7 } }));
    await page.route(`**/api/${api}/evidence?*`, route => route.fulfill({ json: { ...supported, verification: "evidence", evidence: { request: { prompt: "keyboard evidence canary" }, signal: "validated" } } }));
    await page.goto(path);
    await page.getByRole("button", { name: "Expand all", exact: true }).click();
    const result = page.getByRole("table").getByRole("button", { name: "Supported", exact: true });
    await result.click();
    const dialog = page.getByRole("dialog", { name: "Execution evidence", exact: true });
    const details = dialog.locator("details").filter({ hasText: "keyboard evidence canary" });
    const summary = details.locator("summary");
    await expect(summary).toBeVisible();
    await expect(details).not.toHaveAttribute("open");
    await dialog.getByRole("button", { name: "Close dialog", exact: true }).focus();
    await page.keyboard.press("Tab");
    await expect(summary).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(details.locator("pre")).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toHaveCount(0);
    await expect(result).toBeFocused();
  });
}

for (const [path, api] of [["/parity", "parity"], ["/claude-features", "features"]]) {
  // v2.44.2: the disclosure was a component created during render, so every countdown re-render replaced
  // the <details> node. An opened section closed again within a second and the focused summary lost focus.
  test(`${path} an opened evidence disclosure stays open and focused across countdown re-renders`, async ({ page }) => {
    const supported = api === "parity" ? { ...parityCell, status: "supported" } : { ...cell, status: "supported", verdict: "match" };
    const run = { id: 8, started_at: new Date().toISOString(), finished_at: new Date().toISOString(), totals: { supported: 1 }, running: false, catalog_version: "fixture" };
    await page.route(`**/api/${api}/latest`, route => route.fulfill({ json: { run, results: [supported], changes: [], drift: [], previous_run_id: 7 } }));
    await page.route(`**/api/${api}/evidence?*`, route => route.fulfill({ json: { ...supported, verification: "evidence", evidence: { request: { prompt: "keyboard evidence canary" }, signal: "validated" } } }));
    await page.goto(path);
    await page.getByRole("button", { name: "Expand all", exact: true }).click();
    await page.getByRole("table").getByRole("button", { name: "Supported", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Execution evidence", exact: true });
    const details = dialog.locator("details").filter({ hasText: "keyboard evidence canary" });
    const summary = details.locator("summary");
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(details).toHaveAttribute("open");
    await details.evaluate((node) => { (window as unknown as { __disclosure: Element }).__disclosure = node; });
    await countdownTicks(page);
    expect(await details.evaluate((node) => node === (window as unknown as { __disclosure: Element }).__disclosure)).toBe(true);
    await expect(details).toHaveAttribute("open");
    await expect(summary).toBeFocused();
  });
}

test("/claude-features Key Findings buttons keep focus across countdown re-renders", async ({ page }) => {
  await page.goto("/claude-features");
  await page.locator("button.ui-panel").filter({ hasText: "Claude Platform" }).click();
  const drawer = page.locator("aside").filter({ hasText: "Key Findings" });
  const model = drawer.getByRole("button", { name: "Claude Fable 5.1", exact: true }).first();
  await model.focus();
  await expect(model).toBeFocused();
  await countdownTicks(page);
  await expect(model).toBeFocused();
});
