import { expect, test, type Page, type Request } from "@playwright/test";
import type {
  ChannelCompare, CostSummary, EfficiencyResponse, MultiChannelReliability,
  OutputLengthResponse, StopReasonResponse,
} from "../src/lib/api";
import { mockApi } from "./fixtures";

const MODEL = "Bedrock Claude Fable 5.1 (Global)";
const SINCE = "2026-09-01T00:00:00Z";

function costSummary(window = "24h", total = 24, name = MODEL): CostSummary {
  return {
    window, since: SINCE, total_cost_usd: total,
    total_input_tokens: 1200, total_output_tokens: 2400,
    rows: [{
      model_id: name, model_name: name, channel: "Bedrock Global", samples: 12,
      input_tokens: 1200, output_tokens: 2400, cost_usd: total,
      avg_cost_per_call_usd: total / 12,
    }],
  };
}

function channelCompare(window = "24h"): ChannelCompare {
  return {
    window, since: SINCE,
    channels: [{ channel: "Bedrock Global", samples: 12, input_tokens: 1200, output_tokens: 2400, cost_usd: 24 }],
  };
}

function reliability(window = "24h", family = "Claude Fable 5.1"): MultiChannelReliability {
  return {
    window, since: SINCE,
    families: [{
      family,
      channels: [{
        channel: "Bedrock Global", samples: 12, success: 11, error: 1, overloaded: 0,
        success_rate: 11 / 12, avg_ttft_ms: 400, p95_ttft_ms: 600,
        avg_latency_ms: 2000, p95_latency_ms: 3000, avg_tps: 80,
        error_buckets: { server: 1 },
      }],
    }],
  };
}

function efficiency(window = "24h", category: string | null = null, name = MODEL): EfficiencyResponse {
  return {
    window, category, since: SINCE,
    models: [{
      model_id: name, model_name: name, samples: 12, success_rate: 1,
      avg_output_tokens: 200, avg_input_tokens: 100, avg_cost_usd: 2,
      avg_total_latency_ms: 2000, avg_tps: 80, score: 85,
      components: { cost: 0.8, output_tokens: 0.9, latency: 0.8, tps: 0.8, success_rate: 1 },
    }],
  };
}

function stopReasons(window = "7d", category: string | null = null, name = MODEL): StopReasonResponse {
  return {
    window, category,
    rows: [{ model_id: name, model_name: name, total: 12, counts: { end_turn: 9, max_tokens: 3 }, percentages: { end_turn: 75, max_tokens: 25 } }],
  };
}

function outputLength(window = "7d", category: string | null = null, name = MODEL): OutputLengthResponse {
  return {
    window, category,
    rows: [{
      model_id: name, model_name: name, n: 12, mean: 200, median: 190,
      p50: 190, p95: 400, std: 70, min: 100, max: 450,
      histogram: [{ bin: "0-128", count: 2 }, { bin: "128-256", count: 8 }, { bin: "256-512", count: 2 }],
    }],
  };
}

function signal() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

function resourceAlerts(page: Page) {
  return page.getByRole("alert").filter({ hasText: "Could not load" });
}

/** Release an older request after the new view is visible; cancellation also counts as settled. */
async function delayedResponse(page: Page, pattern: string, json: unknown) {
  const started = signal();
  const release = signal();
  const settled = signal();
  let heldRequest: Request | undefined;
  const onSettled = (request: Request) => {
    if (request === heldRequest) settled.resolve();
  };
  page.on("requestfinished", onSettled);
  page.on("requestfailed", onSettled);
  await page.route(pattern, async (route) => {
    heldRequest = route.request();
    started.resolve();
    await release.promise;
    await route.fulfill({ json });
  });
  return {
    started: started.promise,
    release: release.resolve,
    async finish() {
      release.resolve();
      await settled.promise;
      // Let response parsing and React's resulting render finish before checking for an overwrite.
      await page.evaluate(() => new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      }));
    },
  };
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    if (!localStorage.getItem("lang")) localStorage.setItem("lang", "en");
  });
  await page.route(/\/api\/(?:cost|reliability|efficiency|analysis)\//, (route) => {
    const url = new URL(route.request().url());
    const window = url.searchParams.get("window") ?? "24h";
    const category = url.searchParams.get("category");
    const responses: Record<string, unknown> = {
      "/api/cost/summary": costSummary(window, window === "7d" ? 168 : 24),
      "/api/cost/channel-compare": channelCompare(window),
      "/api/reliability/multi-channel": reliability(window),
      "/api/efficiency/score": efficiency(window, category),
      "/api/analysis/stop-reasons": stopReasons(window, category),
      "/api/analysis/output-length": outputLength(window, category),
    };
    const json = responses[url.pathname];
    return json === undefined ? route.fallback() : route.fulfill({ json });
  });
});

test("reliability keeps the latest period when an older request finishes last", async ({ page }) => {
  const old = await delayedResponse(page, "**/api/reliability/multi-channel?window=7d", reliability("7d", "Older weekly family"));
  await page.route("**/api/reliability/multi-channel?window=6h", (route) =>
    route.fulfill({ json: reliability("6h", "Latest six-hour family") }));
  try {
    await page.goto("/reliability");
    await expect(page.getByRole("heading", { name: "Claude Fable 5.1", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "7d", exact: true }).click();
    await old.started;
    await expect(page.getByRole("heading", { name: "Claude Fable 5.1", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "6h", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Latest six-hour family", exact: true })).toBeVisible();
    await old.finish();
    await expect(page.getByRole("heading", { name: "Latest six-hour family", exact: true })).toBeVisible();
    await expect(page.getByText("Older weekly family", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "6h", exact: true })).toHaveAttribute("aria-pressed", "true");
  } finally {
    old.release();
  }
});

test("efficiency keys results by both period and workload", async ({ page }) => {
  const old = await delayedResponse(page, "**/api/efficiency/score?window=24h&category=reasoning", efficiency("24h", "reasoning", "Older reasoning model"));
  await page.route("**/api/efficiency/score?window=7d&category=code-gen", (route) =>
    route.fulfill({ json: efficiency("7d", "code-gen", "Latest coding model") }));
  try {
    await page.goto("/efficiency");
    await expect(page.getByRole("cell", { name: MODEL, exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Reasoning", exact: true }).click();
    await old.started;
    await expect(page.getByRole("cell", { name: MODEL, exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Code generation", exact: true }).click();
    await page.getByRole("button", { name: "7d", exact: true }).click();
    await expect(page.getByRole("cell", { name: "Latest coding model", exact: true })).toBeVisible();
    await old.finish();
    await expect(page.getByRole("cell", { name: "Latest coding model", exact: true })).toBeVisible();
    await expect(page.getByText("Older reasoning model", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Code generation", exact: true })).toHaveAttribute("aria-pressed", "true");
  } finally {
    old.release();
  }
});

test("analysis clears old-filter data and keeps the latest period and workload in both sections", async ({ page }) => {
  const oldStop = await delayedResponse(page, "**/api/analysis/stop-reasons?window=7d&category=reasoning", stopReasons("7d", "reasoning", "Older reasoning model"));
  const oldLength = await delayedResponse(page, "**/api/analysis/output-length?window=7d&category=reasoning", outputLength("7d", "reasoning", "Older reasoning model"));
  await page.route("**/api/analysis/stop-reasons?window=24h&category=code-gen", (route) =>
    route.fulfill({ json: stopReasons("24h", "code-gen", "Latest coding model") }));
  await page.route("**/api/analysis/output-length?window=24h&category=code-gen", (route) =>
    route.fulfill({ json: outputLength("24h", "code-gen", "Latest coding model") }));
  try {
    await page.goto("/analysis");
    await expect(page.getByText(MODEL, { exact: true })).toHaveCount(2);
    await page.getByRole("combobox").selectOption("reasoning");
    await Promise.all([oldStop.started, oldLength.started]);
    await expect(page.getByText(MODEL, { exact: true })).toHaveCount(0);
    await page.getByRole("combobox").selectOption("code-gen");
    await page.getByRole("button", { name: "24h", exact: true }).click();
    await expect(page.getByText("Latest coding model", { exact: true })).toHaveCount(2);
    await Promise.all([oldStop.finish(), oldLength.finish()]);
    await expect(page.getByText("Latest coding model", { exact: true })).toHaveCount(2);
    await expect(page.getByText("Older reasoning model", { exact: true })).toHaveCount(0);
  } finally {
    oldStop.release();
    oldLength.release();
  }
});

test("cost projection never divides a cached seven-day total by the newly selected day", async ({ page }) => {
  await page.goto("/cost");
  const projection = page.getByText("30-day projection", { exact: true }).first().locator("..");
  await expect(projection).toContainText("$720.0000");
  await page.getByRole("button", { name: "7d", exact: true }).click();
  await expect(page.getByText("Total cost", { exact: true }).locator("..")).toContainText("$168.0000");
  await expect(projection).toContainText("$720.0000");
  const day = await delayedResponse(page, "**/api/cost/summary?window=24h", costSummary("24h", 48));
  try {
    await page.getByRole("button", { name: "24h", exact: true }).click();
    await day.started;
    await expect(projection).toContainText("—");
    await expect(projection).not.toContainText("$5040.0000");
    await day.finish();
    await expect(projection).toContainText("$1440.0000");
  } finally {
    day.release();
  }
});

for (const failed of ["summary", "channel-compare"]) {
  test(`cost preserves the companion section when ${failed} fails`, async ({ page }) => {
    await page.route(`**/api/cost/${failed}*`, (route) => route.fulfill({ status: 503, json: { detail: "Unavailable" } }));
    await page.goto("/cost");
    if (failed === "summary") {
      const comparison = page.getByRole("heading", { name: "Channel comparison", exact: true }).locator("..");
      await expect(comparison.getByText("$24.0000", { exact: true })).toBeVisible();
    } else {
      await expect(page.getByRole("cell", { name: MODEL, exact: true })).toBeVisible();
      await expect(page.getByText("Total cost", { exact: true }).locator("..")).toContainText("$24.00");
    }
    await expect(resourceAlerts(page)).toBeVisible();
    await expect(page.getByText(/No data/i)).toHaveCount(0);
  });
}

for (const failed of ["stop-reasons", "output-length"]) {
  test(`analysis preserves the companion section when ${failed} fails`, async ({ page }) => {
    await page.route(`**/api/analysis/${failed}*`, (route) => route.fulfill({ status: 503, json: { detail: "Unavailable" } }));
    await page.goto("/analysis");
    await expect(page.getByText(MODEL, { exact: true })).toHaveCount(1);
    await expect(resourceAlerts(page)).toBeVisible();
    await expect(page.getByText(/No data/i)).toHaveCount(0);
  });
}

test("an HTTP error is distinct from empty results, and retry can reach an empty success", async ({ page }) => {
  let failing = true;
  await page.route("**/api/reliability/multi-channel*", (route) => route.fulfill(failing
    ? { status: 503, json: { detail: "Unavailable" } }
    : { json: { ...reliability(), families: [] } }));
  await page.goto("/reliability");
  await expect(resourceAlerts(page)).toBeVisible();
  await expect(page.getByText(/No data/i)).toHaveCount(0);
  failing = false;
  await resourceAlerts(page).getByRole("button", { name: "Retry", exact: true }).click();
  await expect(resourceAlerts(page)).toHaveCount(0);
  await expect(page.getByText("No data matches these filters.", { exact: true })).toBeVisible();
});

for (const panel of [
  { path: "/cost", endpoint: "/api/cost/summary", result: MODEL },
  { path: "/reliability", endpoint: "/api/reliability/multi-channel", result: "Claude Fable 5.1" },
  { path: "/efficiency", endpoint: "/api/efficiency/score", result: MODEL },
  { path: "/analysis", endpoint: "/api/analysis/stop-reasons", result: MODEL },
]) {
  test(`${panel.path} retains same-filter data after a failed refresh and supports retry`, async ({ page }) => {
    let failing = false;
    await page.route(`**${panel.endpoint}*`, (route) => failing
      ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
      : route.fallback());
    await page.goto(panel.path);
    await expect(page.getByText(panel.result, { exact: true }).first()).toBeVisible();
    const refresh = page.getByRole("button", { name: "Refresh", exact: true });
    await expect(refresh).toBeEnabled();
    const lastChecked = page.getByText(/^Last checked:/);
    await expect(lastChecked).not.toContainText("Not checked yet");
    const successfulCheck = await lastChecked.textContent();
    failing = true;
    await refresh.click();
    await expect(resourceAlerts(page)).toContainText("Showing the last successful result.");
    await expect(page.getByText(panel.result, { exact: true }).first()).toBeVisible();
    await expect(lastChecked).toHaveText(successfulCheck!);
    await expect(page.getByText(/No data/i)).toHaveCount(0);
    failing = false;
    await resourceAlerts(page).getByRole("button", { name: "Retry", exact: true }).click();
    await expect(resourceAlerts(page)).toHaveCount(0);
    await expect(page.getByText(panel.result, { exact: true }).first()).toBeVisible();
  });
}

for (const path of ["/efficiency", "/analysis"]) {
  test(`${path} reports a workload catalog failure without discarding measurements`, async ({ page }) => {
    let failing = true;
    await page.route("**/api/auto-probe/categories", (route) => failing
      ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
      : route.fallback());
    await page.goto(path);
    await expect(page.getByText(MODEL, { exact: true }).first()).toBeVisible();
    await expect(resourceAlerts(page)).toContainText(/workload/i);
    failing = false;
    await resourceAlerts(page).getByRole("button", { name: "Retry", exact: true }).click();
    await expect(resourceAlerts(page)).toHaveCount(0);
    if (path === "/efficiency") {
      await expect(page.getByRole("button", { name: "Reasoning", exact: true })).toBeVisible();
    } else {
      await expect(page.getByRole("combobox").getByRole("option", { name: "Reasoning", exact: true })).toHaveCount(1);
    }
  });
}

test("automatic refresh runs every 30 seconds and can be paused", async ({ page }) => {
  await page.clock.install();
  let total = 24;
  await page.route("**/api/cost/summary*", (route) => route.fulfill({ json: costSummary("24h", total) }));
  await page.goto("/cost");
  const card = page.getByText("Total cost", { exact: true }).locator("..");
  await expect(card).toContainText("$24.00");
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  const automatic = page.getByRole("checkbox", { name: /Auto refresh/ });
  await expect(automatic).toBeChecked();
  total = 48;
  await page.clock.fastForward(30_000);
  await expect(card).toContainText("$48.00");
  await automatic.uncheck();
  total = 72;
  await page.clock.fastForward(60_000);
  await expect(card).toContainText("$48.00");
  await automatic.check();
  await page.clock.fastForward(30_000);
  await expect(card).toContainText("$72.00");
});

for (const panel of [
  { path: "/cost", title: "Cost Dashboard", ko: "비용 대시보드" },
  { path: "/reliability", title: "Multi-channel Reliability", ko: "다중 채널 신뢰성" },
  { path: "/efficiency", title: "Token Efficiency", ko: "토큰 효율성" },
  { path: "/analysis", title: "Output Analysis", ko: "출력 분석" },
]) {
  test(`${panel.path} has accessible filters and fits mobile in both themes and languages`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(panel.path);
    await expect(page.getByRole("heading", { name: panel.title, level: 1, exact: true })).toBeVisible();
    const selected = page.getByRole("group", { name: "Window", exact: true }).locator("button[aria-pressed='true']");
    await expect(selected).toHaveCount(1);
    await selected.focus();
    await page.keyboard.press("Tab");
    const focusedOutline = await page.evaluate(() => {
      const style = getComputedStyle(document.activeElement!);
      return style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0;
    });
    expect(focusedOutline).toBe(true);
    for (const theme of ["dark", "light"]) {
      await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
    await page.evaluate(() => localStorage.setItem("lang", "ko"));
    await page.reload();
    await expect(page.getByRole("heading", { name: panel.ko, level: 1, exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "새로고침", exact: true })).toBeVisible();
    await expect(page.getByRole("group", { name: "기간", exact: true }).locator("button[aria-pressed='true']")).toHaveCount(1);
    for (const theme of ["dark", "light"]) {
      await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
  });
}
