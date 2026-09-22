import { expect, test } from "@playwright/test";
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
