import { expect, test, type Page } from "@playwright/test";
import type { GptBenchLatest, GptBenchTrend } from "../src/lib/api";
import { mockApi } from "./fixtures";

const catalog = [
  { id: "anthropic:claude-fable-5-1", name: "Anthropic Claude Fable 5.1 (US)" },
  { id: "global.anthropic.claude-fable-5-1", name: "Bedrock Claude Fable 5.1 (Global)" },
  { id: "openai:us:us.openai.gpt-6-astra", name: "OpenAI GPT 6 Astra (US)" },
];

function benchmarkData(): { latest: GptBenchLatest; trend: GptBenchTrend } {
  const cycle = new Date(Date.now() - 20 * 60_000).toISOString();
  // 18채널 (v2.28.0) — /api/gptbench/latest 정렬(Astra → Sol → Luna → Terra → 5.5 → 5.4)과 동일.
  const families = [
    ["GPT 6 Astra", ["Global", "US", "us-west-2"]],
    ["GPT 6 Sol", ["Global", "US", "us-east-1"]],
    ["GPT 6 Luna", ["Global", "US", "us-east-1"]],
    ["GPT 5.6 Terra", ["Global", "us-east-1", "us-east-2", "us-west-2"]],
    ["GPT 5.5", ["us-east-1", "us-east-2"]],
    ["GPT 5.4", ["us-east-1", "us-east-2", "us-west-2"]],
  ] as const;
  const channels = families.flatMap(([family, regions]) => regions.map((region) => ({
    model_id: `${family}:${region}`, model_name: `OpenAI ${family} (${region})`,
    family, region, runs: 10, success: 10, median_ttfb_ms: 800,
    median_ttft_ms: 1800, median_gap_ms: 1000, p95_ttft_ms: 2200,
    cache_hit_rate: 1, median_reasoning_tokens: 100, last_error: null,
  })));
  return {
    latest: { cycle_ts: cycle, channels },
    trend: {
      hours: 24,
      series: channels.map((channel) => ({
        model_id: channel.model_id, model_name: channel.model_name,
        points: [30, 15, 0].map((minutes) => ({
          cycle_ts: new Date(Date.parse(cycle) - minutes * 60_000).toISOString(),
          median_ttfb_ms: 800 + minutes, median_ttft_ms: 1800 + minutes,
          median_gap_ms: 1000, errors: 0,
        })),
      })),
    },
  };
}

async function mockBenchmark(page: Page) {
  const data = benchmarkData();
  await page.route("**/api/gptbench/latest", (route) => route.fulfill({ json: data.latest }));
  await page.route("**/api/gptbench/trend?*", (route) => route.fulfill({
    json: { ...data.trend, hours: Number(new URL(route.request().url()).searchParams.get("hours")) },
  }));
  return data;
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => localStorage.setItem("lang", "en"));
  await page.route("**/api/models", (route) => route.fulfill({ json: catalog }));
});

test("benchmark cards show all 18 channels grouped by generation", async ({ page }) => {
  const data = await mockBenchmark(page);
  expect(data.latest.channels).toHaveLength(18);
  await page.goto("/gpt-on-aws");
  const cards = page.getByRole("region", { name: "Benchmark cards", exact: true });
  for (const channel of data.latest.channels) {
    await expect(cards.getByRole("button", { name: channel.model_name, exact: true })).toBeVisible();
  }
  const gpt6 = cards.getByRole("group", { name: "GPT 6 generation", exact: true });
  const gpt5 = cards.getByRole("group", { name: "GPT 5.x generation", exact: true });
  await expect(gpt6.getByRole("heading", { level: 3 })).toHaveText(["GPT 6 Astra", "GPT 6 Sol", "GPT 6 Luna"]);
  await expect(gpt5.getByRole("heading", { level: 3 })).toHaveText(["GPT 5.6 Terra", "GPT 5.5", "GPT 5.4"]);
  await expect(gpt6.getByRole("button")).toHaveCount(9);
  await expect(gpt5.getByRole("button")).toHaveCount(9);
  for (const name of ["OpenAI GPT 6 Sol (Global)", "OpenAI GPT 6 Sol (US)", "OpenAI GPT 6 Sol (us-east-1)",
    "OpenAI GPT 6 Luna (Global)", "OpenAI GPT 6 Luna (US)", "OpenAI GPT 6 Luna (us-east-1)"]) {
    await expect(gpt6.getByRole("button", { name, exact: true })).toBeVisible();
  }
  await expect(cards.getByRole("group", { name: "Other", exact: true })).toHaveCount(0);
  const legend = page.getByRole("list", { name: "Chart legend" }).first();
  await expect(legend.getByRole("listitem")).toHaveCount(18);
});

test("benchmark cards with an unknown family land in Other instead of disappearing", async ({ page }) => {
  const data = await mockBenchmark(page);
  data.latest.channels = [...data.latest.channels, {
    ...data.latest.channels[0], model_id: "GPT 7 Nova:US", model_name: "OpenAI GPT 7 Nova (US)", family: "GPT 7 Nova",
  }];
  await page.goto("/gpt-on-aws");
  const other = page.getByRole("group", { name: "Other", exact: true });
  await expect(other.getByRole("button", { name: "OpenAI GPT 7 Nova (US)", exact: true })).toBeVisible();
  await expect(other.getByRole("button")).toHaveCount(1);
});

test("a trend failure keeps benchmark cards and offers an independent retry", async ({ page }) => {
  await mockBenchmark(page);
  let fail = true;
  await page.route("**/api/gptbench/trend?*", (route) => fail
    ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
    : route.fallback());
  await page.goto("/gpt-on-aws");
  await expect(page.getByRole("button", { name: "OpenAI GPT 6 Astra (US)", exact: true })).toBeVisible();
  const error = page.getByRole("alert").filter({ hasText: "benchmark trends" });
  await expect(error).toBeVisible();
  await expect(page.getByText("No benchmark data yet.", { exact: true })).toHaveCount(0);
  fail = false;
  await error.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(error).toHaveCount(0);
  await expect(page.locator(".recharts-wrapper")).toHaveCount(3);
});

test("a latest failure keeps benchmark trends and offers an independent retry", async ({ page }) => {
  await mockBenchmark(page);
  let fail = true;
  await page.route("**/api/gptbench/latest", (route) => fail
    ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
    : route.fallback());
  await page.goto("/gpt-on-aws");
  await expect(page.locator(".recharts-wrapper")).toHaveCount(3);
  const error = page.getByRole("alert").filter({ hasText: "benchmark cards" });
  await expect(error).toBeVisible();
  fail = false;
  await error.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("button", { name: "OpenAI GPT 6 Astra (US)", exact: true })).toBeVisible();
});

test("changing benchmark range discards late responses without reloading cards", async ({ page }) => {
  const data = await mockBenchmark(page);
  let latestRequests = 0;
  await page.route("**/api/gptbench/latest", (route) => {
    latestRequests += 1;
    return route.fallback();
  });
  let release!: () => void;
  let finish!: () => void;
  let started!: () => void;
  const pending = new Promise<void>((resolve) => { release = resolve; });
  const finished = new Promise<void>((resolve) => { finish = resolve; });
  const requested = new Promise<void>((resolve) => { started = resolve; });
  await page.route("**/api/gptbench/trend?hours=6", async (route) => {
    started();
    await pending;
    try {
      await route.fulfill({ json: { hours: 6, series: [data.trend.series[0]] } });
    } finally {
      finish();
    }
  });
  await page.route("**/api/gptbench/trend?hours=3", (route) => route.fulfill({
    json: { hours: 3, series: [data.trend.series[1]] },
  }));
  await page.goto("/gpt-on-aws");
  await expect(page.locator(".recharts-wrapper")).toHaveCount(3);
  const initialRequests = latestRequests;
  const card = page.getByRole("button", { name: "OpenAI GPT 6 Astra (US)", exact: true });
  try {
    await page.getByRole("button", { name: "6h", exact: true }).click();
    await requested;
    await expect(card).toBeVisible();
    await page.getByRole("button", { name: "3h", exact: true }).click();
    const legend = page.getByRole("list", { name: "Chart legend" }).first();
    await expect(legend).toContainText("OpenAI GPT 6 Astra (US)");
    release();
    await finished;
    await expect(legend).not.toContainText("Global");
    await expect(page.getByRole("button", { name: "3h", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(latestRequests).toBe(initialRequests);
  } finally {
    release();
  }
});

test("benchmark refresh preserves selection and collection age continues while paused", async ({ page }) => {
  const now = new Date("2026-09-22T12:00:00Z");
  await page.clock.install({ time: now });
  const data = await mockBenchmark(page);
  data.latest.cycle_ts = "2026-09-22T11:31:00Z";
  await page.goto("/gpt-on-aws");
  const card = page.getByRole("button", { name: "OpenAI GPT 6 Astra (US)", exact: true });
  await expect(card).toHaveAttribute("aria-pressed", "true");
  await card.click();
  const other = page.getByRole("button", { name: "OpenAI GPT 6 Astra (Global)", exact: true });
  await expect(other).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  await expect(other).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("checkbox", { name: /Auto refresh/ }).uncheck();
  await expect(page.getByText("Collection delayed", { exact: true })).toHaveCount(0);
  await page.clock.fastForward(65_000);
  await expect(page.getByText("Collection delayed", { exact: true })).toBeVisible();
  await expect(page.locator('time[datetime="2026-09-22T11:31:00.000Z"]')).toBeVisible();
});

test("benchmark charts use elapsed time and keep failed or missing cycles as gaps", async ({ page }) => {
  const data = await mockBenchmark(page);
  const times = ["2026-09-20T23:00:00", "2026-09-20T23:15:00", "2026-09-20T23:45:00", "2026-09-21T01:00:00"];
  data.trend.series = data.trend.series.slice(0, 2).map((series, seriesIndex) => ({
    ...series,
    points: times.flatMap((cycle_ts, index) => seriesIndex === 1 && index === 2 ? [] : [{
      cycle_ts, median_ttfb_ms: index === 2 ? null : index === 0 ? 0 : index === 1 ? 1000 : 2000,
      median_ttft_ms: index === 2 ? null : 2200, median_gap_ms: null, errors: index === 2 ? 10 : 0,
    }]),
  }));
  await page.goto("/gpt-on-aws");
  const chart = page.getByRole("region", { name: "TTFB trend (median per cycle)", exact: true });
  await expect(chart.locator(".recharts-line-curve")).toHaveCount(2);
  expect((await chart.locator(".recharts-line-curve").first().getAttribute("d"))?.match(/M/g)).toHaveLength(2);
  await page.getByRole("button", { name: "OpenAI GPT 6 Astra (US)", exact: true }).click();
  await expect(chart.locator(".recharts-line-curve")).toHaveCount(1);
  expect((await chart.locator(".recharts-line-curve").getAttribute("d"))?.match(/M/g)).toHaveLength(2);
  const dots = chart.locator(".recharts-line-dot");
  await expect(dots).toHaveCount(3);
  const x = await dots.evaluateAll((nodes) => nodes.map((node) => Number(node.getAttribute("cx"))));
  expect((x[1] - x[0]) / (x[2] - x[0])).toBeCloseTo(0.125, 2);
  await expect(chart.locator(".recharts-xAxis")).toContainText("Sep");
  await dots.first().hover();
  await expect(chart.locator(".recharts-tooltip-wrapper")).toContainText("0ms");
  await expect(chart.locator(".recharts-tooltip-wrapper")).toContainText("Sep 20");
  const gap = page.getByRole("region", { name: "GAP (thinking) trend", exact: true });
  await expect(gap.getByText("No measurements for this metric.", { exact: true })).toBeVisible();
  await expect(gap.locator(".recharts-wrapper")).toHaveCount(0);
  await page.locator('header button[lang="ko"]:visible').click();
  await expect(chart.locator(".recharts-xAxis")).toHaveCount(0);
  const koreanChart = page.getByRole("region", { name: "TTFB 추이 (사이클 median)", exact: true });
  await expect(koreanChart.locator(".recharts-xAxis")).toContainText("9월");
});

test("dense benchmark charts keep isolated successes without ordinary marker nodes", async ({ page }) => {
  const data = await mockBenchmark(page);
  const latest = Date.parse(data.latest.cycle_ts!);
  // 96 shared cycles across 18 channels exceed the 700-point marker limit.
  data.trend.series = data.trend.series.map((series, channel) => ({
    ...series,
    points: Array.from({ length: 96 }, (_, index) => {
      const success = channel !== 0 || index === 47;
      return {
        cycle_ts: new Date(latest - (95 - index) * 15 * 60_000).toISOString(),
        median_ttfb_ms: success ? (channel === 0 ? 0 : 800) : null,
        median_ttft_ms: success ? 1800 : null,
        median_gap_ms: success ? (channel === 0 ? 1800 : 1000) : null,
        errors: success ? 0 : 10,
      };
    }),
  }));
  await page.goto("/gpt-on-aws");
  const chart = page.getByRole("region", { name: "TTFB trend (median per cycle)", exact: true });
  const marker = chart.locator(".recharts-line-dots circle");
  await expect(marker).toHaveCount(1);
  await expect(marker).toBeVisible();
  await expect(chart.locator(".recharts-line-dots > *")).toHaveCount(1);
  await marker.hover();
  await expect(chart.locator(".recharts-tooltip-wrapper")).toContainText("0ms");
});

test("empty benchmark results retain refresh and time range controls", async ({ page }) => {
  const data = await mockBenchmark(page);
  data.latest = { cycle_ts: null, channels: [] };
  data.trend.series = [];
  await page.goto("/gpt-on-aws");
  await expect(page.getByText("No benchmark data yet.", { exact: true })).toBeVisible();
  await expect(page.getByText("No trend data in this time range.", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "7d", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "Refresh", exact: true })).toBeEnabled();
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
});

test("catalog request errors are recoverable and do not appear as an empty catalog", async ({ page }) => {
  let fail = true;
  await page.route("**/api/models", (route) => fail
    ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
    : route.fallback());
  await page.goto("/models");
  await expect(page.getByRole("heading", { name: "Model Explorer", exact: true })).toBeVisible();
  const error = page.getByRole("alert").filter({ hasText: "model catalog" });
  await expect(error).toBeVisible();
  await expect(page.getByText("No models available.", { exact: true })).toHaveCount(0);
  fail = false;
  await error.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(page.getByRole("button", { name: catalog[0].name, exact: true })).toBeVisible();
});

test("catalog refresh retains filters and last good cards after a failure", async ({ page }) => {
  let fail = false;
  await page.route("**/api/models", (route) => fail
    ? route.fulfill({ status: 503, json: { detail: "Unavailable" } })
    : route.fallback());
  await page.goto("/models");
  const search = page.getByRole("searchbox", { name: "Search models", exact: true });
  await search.fill("Fable");
  const channel = page.getByRole("button", { name: "Bedrock", exact: true });
  await channel.click();
  await expect(channel).toHaveAttribute("aria-pressed", "true");
  const card = page.getByRole("button", { name: catalog[1].name, exact: true });
  await expect(card).toBeVisible();
  fail = true;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  const error = page.getByRole("alert").filter({ hasText: "model catalog" });
  await expect(error).toBeVisible();
  await expect(card).toBeVisible();
  await expect(search).toHaveValue("Fable");
  await expect(channel).toHaveAttribute("aria-pressed", "true");
  fail = false;
  await error.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(error).toHaveCount(0);
  await expect(card).toBeVisible();
});

test("catalog distinguishes an empty catalog from filters with no matches", async ({ page }) => {
  let empty = true;
  await page.route("**/api/models", (route) => empty ? route.fulfill({ json: [] }) : route.fallback());
  await page.goto("/models");
  await expect(page.getByText("No models available.", { exact: true })).toBeVisible();
  empty = false;
  await page.getByRole("button", { name: "Refresh", exact: true }).click();
  await page.getByRole("searchbox", { name: "Search models", exact: true }).fill("missing-model");
  await expect(page.getByText("No models match these filters.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Reset filters", exact: true }).click();
  await expect(page.getByRole("button", { name: catalog[0].name, exact: true })).toBeVisible();
});

test("catalog details support keyboard tabs, copy feedback and focus return", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: {
      writeText: async () => { throw new DOMException("Denied", "NotAllowedError"); },
    } });
  });
  await page.goto("/models");
  const card = page.getByRole("button", { name: catalog[1].name, exact: true });
  await card.focus();
  await card.press("Enter");
  const dialog = page.getByRole("dialog", { name: catalog[1].name, exact: true });
  await expect(dialog).toBeVisible();
  const close = dialog.getByRole("button", { name: "Close dialog", exact: true });
  await expect(close).toBeFocused();
  await page.locator('input[type="search"]').evaluate((element) => (element as HTMLInputElement).focus());
  await expect(close).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(dialog.getByRole("button", { name: "Copy model ID", exact: true })).toBeFocused();
  const tab = dialog.getByRole("tab", { name: "Converse API", exact: true });
  await tab.focus();
  await tab.press("ArrowRight");
  await expect(dialog.getByRole("tab", { name: "InvokeModel API", exact: true })).toBeFocused();
  await expect(dialog.getByRole("tabpanel")).toContainText("client.invoke_model");
  await dialog.getByRole("button", { name: "Copy model ID", exact: true }).click();
  await expect(dialog.getByRole("status").filter({ hasText: "Copy failed" })).toBeVisible();
  await page.evaluate(() => {
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText: async () => {} } });
  });
  await dialog.getByRole("button", { name: "Copy model ID", exact: true }).click();
  await expect(dialog.getByRole("status").filter({ hasText: "Copied to clipboard" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(card).toBeFocused();
  await card.press("Space");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "Close dialog", exact: true }).click();
  await expect(card).toBeFocused();
  expect(errors).toEqual([]);
});

test("benchmark legends and catalog dialogs fit a mobile viewport in both themes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockBenchmark(page);
  await page.goto("/gpt-on-aws");
  const card = page.getByRole("button", { name: "OpenAI GPT 6 Astra (US)", exact: true });
  await expect(card).toBeVisible();
  expect((await card.boundingBox())!.width).toBeGreaterThan(330);
  const chart = page.getByRole("region", { name: "TTFB trend (median per cycle)", exact: true });
  const plot = await chart.locator(".recharts-wrapper").boundingBox();
  const legend = await chart.getByRole("list", { name: "Chart legend" }).boundingBox();
  expect(plot!.height).toBeGreaterThanOrEqual(250);
  expect(legend!.y).toBeGreaterThanOrEqual(plot!.y + plot!.height);
  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
  await page.goto("/models");
  await page.getByRole("button", { name: catalog[1].name, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: catalog[1].name, exact: true });
  await expect(dialog).toBeVisible();
  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
    expect(await dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  }
});
