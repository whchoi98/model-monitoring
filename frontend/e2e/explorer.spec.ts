import { expect, test, type Page } from "@playwright/test";
import { explorerLatest, explorerResult } from "./explorerFixtures";
import { mockApi } from "./fixtures";

// Model Explorer daily verification (v2.40.0, ADR-035): badges, run-to-run changes, the verification box and the
// fallback when /api/explorer/latest fails. All APIs are fixtures.

const OPUS = { id: "global.anthropic.claude-opus-5", name: "Bedrock Claude Opus 5 (Global)" };
const NOVA = { id: "us.amazon.nova-2-lite-v1:0", name: "Bedrock Nova 2.0 Lite (US)" };
const CP = { id: "anthropic:claude-sonnet-5-5", name: "Anthropic Claude Sonnet 5.5 (US)" };
const CATALOG = [CP, OPUS, NOVA];

const RESULTS = {
  [`${OPUS.id}|converse`]: explorerResult("passed"),
  [`${OPUS.id}|invoke_model`]: explorerResult("failed"),
  [`${OPUS.id}|messages`]: explorerResult("passed", { stale_code: true }),
  [`${NOVA.id}|converse`]: explorerResult("passed"),
};
const CHANGES = [
  { model_id: OPUS.id, model_name: OPUS.name, api_id: "invoke_model", api: "InvokeModel API", before: "passed" as const, after: "failed" as const, kind: "measured" as const },
  { model_id: "global.anthropic.claude-retired", model_name: "Bedrock Claude Retired (Global)", api_id: "converse", api: "Converse API", before: null, after: "passed" as const, kind: "catalog" as const },
];

async function mockExplorer(page: Page, body: unknown) {
  await page.route("**/api/models", (route) => route.fulfill({ json: CATALOG }));
  await page.route("**/api/explorer/latest", (route) => route.fulfill({ json: body }));
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem("lang", "en"));
  await page.clock.setFixedTime(new Date("2026-11-05T20:00:00Z"));
});

test("cards show the verification badge and the change marker", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS, changes: CHANGES }));
  await page.goto("/models");
  const opus = page.getByRole("button", { name: OPUS.name, exact: true });
  await expect(opus.locator("[data-verify-badge]")).toHaveText("✗ 1/3 failed");
  await expect(opus.locator("[data-verify-badge]")).toHaveAttribute("data-verify-badge", "failed");
  await expect(opus.locator("[data-verify-changed]")).toHaveText("Changed");
  const nova = page.getByRole("button", { name: NOVA.name, exact: true });
  await expect(nova.locator("[data-verify-badge]")).toHaveText("✓ 1/1 passed");
  await expect(nova.locator("[data-verify-changed]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: CP.name, exact: true }).locator("[data-verify-badge]")).toHaveText("Not verified");
  await expect(page.locator("[data-explorer-run]")).toContainText("Last verification run #12");
  await expect(page.locator("[data-explorer-run]")).toContainText("passed 83, failed 1, skipped 1");
});

test("the change banner opens the model on the changed API tab and leaves a model off the page as text", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS, changes: CHANGES }));
  await page.goto("/models");
  const banner = page.locator("details[data-explorer-changes]");
  await expect(banner.locator("summary")).toHaveText("Changes since run #11: 2");
  await banner.locator("summary").click();
  await expect(banner).toContainText("New 1, example changed 0, measured 1");
  await expect(banner.getByRole("button", { name: "Bedrock Claude Retired (Global), Converse API" })).toBeDisabled();
  await banner.getByRole("button", { name: `${OPUS.name}, InvokeModel API` }).click();
  const dialog = page.getByRole("dialog", { name: OPUS.name, exact: true });
  await expect(dialog.getByRole("tab", { name: "InvokeModel API", exact: true })).toHaveAttribute("aria-selected", "true");
  const box = dialog.locator('[data-verify="failed"]');
  await expect(box).toContainText("Still failing after a retry");
  await expect(box).toContainText("KeyError: 'text'");
  await expect(box.getByText("Traceback (most recent call last):")).toBeHidden();
  await box.getByText("Error output", { exact: true }).click();
  await expect(box.getByText(/Traceback \(most recent call last\):/)).toBeVisible();
});

test("the modal shows a passing result with its output and a stale-code notice", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS }));
  await page.goto("/models");
  await page.getByRole("button", { name: OPUS.name, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: OPUS.name, exact: true });
  const passed = dialog.locator('[data-verify="passed"]');
  await expect(passed).toContainText("Verified, 1.2 s");
  await expect(passed).toContainText("(run #12)");
  await expect(passed).toContainText("Hello! How can I help you today?");
  await expect(dialog.getByRole("tabpanel")).toContainText('region_name="ap-northeast-2"');
  await dialog.getByRole("tab", { name: "Messages API", exact: true }).click();
  await expect(dialog.locator('[data-verify="passed"]')).toContainText("This example changed after the last verification (run #12).");
});

test("no previous run shows no banner, a run with no change shows the no-change card", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { previousRunId: null }));
  await page.goto("/models");
  await expect(page.getByRole("button", { name: OPUS.name, exact: true })).toBeVisible();
  await expect(page.locator("[data-explorer-changes]")).toHaveCount(0);
  await page.unroute("**/api/explorer/latest");
  await page.route("**/api/explorer/latest", (route) => route.fulfill({ json: explorerLatest(CATALOG) }));
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.locator("[data-explorer-changes]")).toHaveText("No changes since run #11.");
});

test("failures only keeps the models with a failed example and the reset clears it", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS }));
  await page.goto("/models");
  const toggle = page.getByRole("button", { name: "Failures only", exact: true });
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("1 / 3 models", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: OPUS.name, exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: NOVA.name, exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Reset filters", exact: true }).click();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByText("3 / 3 models", { exact: true })).toBeVisible();
});

test("an explorer API failure keeps the cards and retries inside the modal", async ({ page }) => {
  let fail = true;
  await page.route("**/api/models", (route) => route.fulfill({ json: CATALOG }));
  await page.route("**/api/explorer/latest", (route) => fail
    ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
    : route.fulfill({ json: explorerLatest(CATALOG, { results: RESULTS }) }));
  await page.goto("/models");
  const card = page.getByRole("button", { name: OPUS.name, exact: true });
  await expect(card).toBeVisible();
  await expect(card.locator("[data-verify-badge]")).toHaveCount(0);
  await card.click();
  const dialog = page.getByRole("dialog", { name: OPUS.name, exact: true });
  const alert = dialog.getByRole("alert").filter({ hasText: "code examples" });
  await expect(alert).toBeVisible();
  fail = false;
  await alert.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(dialog.getByRole("tab", { name: "Converse API", exact: true })).toBeVisible();
  await expect(dialog.locator('[data-verify="passed"]')).toBeVisible();
});

test("the run button asks a signed-out visitor to log in", async ({ page }) => {
  await mockExplorer(page, explorerLatest(CATALOG));
  await page.goto("/models");
  await page.getByRole("button", { name: "Run verification", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Login", exact: true })).toBeVisible();
});

test("Korean copy at 390px without horizontal page scroll", async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("lang", "ko"));
  await page.setViewportSize({ width: 390, height: 844 });
  await mockExplorer(page, explorerLatest(CATALOG, { results: RESULTS, changes: CHANGES }));
  await page.goto("/models");
  await expect(page.getByRole("button", { name: OPUS.name, exact: true }).locator("[data-verify-badge]")).toHaveText("✗ 1/3 실패");
  await expect(page.locator("details[data-explorer-changes] summary")).toHaveText("이전 런(#11) 대비 변경 2건");
  await expect(page.getByRole("button", { name: "검증 실패만", exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});

// A verification run in progress refreshes /api/explorer/latest every 15 s (fake clock), and a page without a run never polls.
const RUN_13 = { id: 13, started_at: "2026-11-05T20:00:00Z", finished_at: "2026-11-05T20:02:00Z", totals: { passed: 85, failed: 0, skipped: 0 } };

test("a run in progress refreshes the result without a reload", async ({ page }) => {
  let finished = false;
  let calls = 0;
  await page.route("**/api/models", (route) => route.fulfill({ json: CATALOG }));
  await page.route("**/api/explorer/latest", (route) => {
    calls += 1;
    return route.fulfill({ json: finished ? explorerLatest(CATALOG, { run: RUN_13 }) : explorerLatest(CATALOG, { running: true }) });
  });
  await page.clock.install({ time: new Date("2026-11-05T20:00:00Z") });
  await page.goto("/models");
  await expect(page.locator("[data-explorer-run]")).toContainText("Last verification run #12");
  await expect(page.locator("[data-explorer-run]")).toContainText("run in progress");
  await expect(page.getByRole("button", { name: "Run verification", exact: true })).toBeDisabled();
  finished = true;
  await page.clock.runFor(16_000);
  await expect(page.locator("[data-explorer-run]")).toContainText("Last verification run #13");
  await expect(page.locator("[data-explorer-run]")).not.toContainText("run in progress");
  await expect(page.getByRole("button", { name: "Run verification", exact: true })).toBeEnabled();
  const settled = calls;
  await page.clock.runFor(60_000);
  expect(calls).toBe(settled);
});

test("after a trigger the page polls until a new run shows up", async ({ page }) => {
  let sinceTrigger = -1;
  let calls = 0;
  await page.addInitScript(() => localStorage.setItem("auth_token", "explorer-fixture-token"));
  await page.route("**/api/auth/me", (route) => route.fulfill({ json: { id: 1, username: "workflow-user" } }));
  await page.route("**/api/models", (route) => route.fulfill({ json: CATALOG }));
  await page.route("**/api/explorer/trigger", (route) => { sinceTrigger = 0; return route.fulfill({ json: { triggered: true, message: "started" } }); });
  await page.route("**/api/explorer/latest", (route) => {
    calls += 1;
    if (sinceTrigger >= 0) sinceTrigger += 1;
    // The refresh right after the trigger still shows run #12 and no run in progress; the next poll shows run #13.
    return route.fulfill({ json: sinceTrigger > 1 ? explorerLatest(CATALOG, { run: RUN_13 }) : explorerLatest(CATALOG) });
  });
  await page.clock.install({ time: new Date("2026-11-05T20:00:00Z") });
  await page.goto("/models");
  await expect(page.locator("[data-explorer-run]")).toContainText("Last verification run #12");
  await page.getByRole("button", { name: "Run verification", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Verification started" })).toBeVisible();
  await expect(page.locator("[data-explorer-run]")).toContainText("#12");
  await page.clock.runFor(16_000);
  await expect(page.locator("[data-explorer-run]")).toContainText("Last verification run #13");
  const settled = calls;
  await page.clock.runFor(60_000);
  expect(calls).toBe(settled);
});

test("a page with no run in progress never polls the verification result", async ({ page }) => {
  let calls = 0;
  await page.route("**/api/models", (route) => route.fulfill({ json: CATALOG }));
  await page.route("**/api/explorer/latest", (route) => { calls += 1; return route.fulfill({ json: explorerLatest(CATALOG) }); });
  await page.clock.install({ time: new Date("2026-11-05T20:00:00Z") });
  await page.goto("/models");
  await expect(page.locator("[data-explorer-run]")).toContainText("#12");
  const settled = calls;
  await page.clock.runFor(120_000);
  expect(calls).toBe(settled);
});
