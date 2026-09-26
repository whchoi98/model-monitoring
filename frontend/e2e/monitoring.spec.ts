import { test, expect, type Page } from "@playwright/test";
import { mockApi, modelCatalog } from "./fixtures";

test("monitoring distinguishes current failures, stale success and an unmeasured model", async ({ page }) => {
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "모델 모니터링", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /확인 필요.*4/ })).toBeVisible();
  await page.getByRole("button", { name: /확인 필요.*4/ }).click();
  const models = page.getByRole("region", { name: "모델별 최신 상태" });
  await expect(models.getByText("수집 지연", { exact: true })).toBeVisible();
  await expect(models.getByText("미수집", { exact: true })).toBeVisible();
  await expect(models.getByRole("button", { name: new RegExp(modelCatalog[0].name.replace(/[()]/g, "\\$&")) })).toHaveCount(0);
});

test("search, sorting and comparison selection survive reload without losing workload or range", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?hours=6&category=reasoning");
  const models = page.getByRole("region", { name: "모델별 최신 상태" });
  const chosen = models.getByRole("button", { name: `${modelCatalog[0].name} 추세 비교 선택`, exact: true });
  await chosen.click();
  await models.getByRole("searchbox", { name: "모델 검색", exact: true }).pressSequentially("astra");
  await expect(models.getByRole("article")).toHaveCount(3);
  await models.getByRole("combobox", { name: "모델 정렬", exact: true }).selectOption("attention");
  await expect(models.getByRole("article").first().getByRole("button")).toHaveAttribute("aria-label", `${modelCatalog[4].name} 추세 비교 선택`);
  await page.reload();
  await expect(models.getByRole("searchbox", { name: "모델 검색", exact: true })).toHaveValue("astra");
  await expect(models.getByRole("combobox", { name: "모델 정렬", exact: true })).toHaveValue("attention");
  await expect(models.getByRole("article")).toHaveCount(3);
  const query = new URL(page.url()).searchParams;
  expect(query.get("hours")).toBe("6");
  expect(query.get("category")).toBe("reasoning");
  expect(query.get("models")).toBe(modelCatalog[0].name);
  await models.getByRole("button", { name: "필터 초기화", exact: true }).click();
  await expect(models.getByRole("article")).toHaveCount(6);
  await expect(chosen).toHaveAttribute("aria-pressed", "true");
});

test("a failed data request has a retry action and is not described as empty data", async ({ page }) => {
  await mockApi(page);
  let fail = true;
  await page.route("**/api/auto-probe/latest*", (route) => fail
    ? route.fulfill({ status: 503, contentType: "application/json", body: '{"detail":"Unavailable"}' })
    : route.fallback());
  await page.goto("/");
  await expect(page.getByRole("alert").filter({ hasText: "최신 모델 상태" })).toBeVisible();
  await expect(page.getByText("아직 자동 프로빙 데이터가 없습니다.")).toHaveCount(0);
  fail = false;
  await page.getByRole("alert").filter({ hasText: "최신 모델 상태" }).getByRole("button", { name: "다시 시도" }).click();
  await expect(page.getByRole("region", { name: "모델별 최신 상태" })).toBeVisible();
});

test("a failed trend does not discard model status, and period controls remain available", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/auto-probe/trend*", (route) => route.fulfill({ status: 503, body: "{}" }));
  await page.goto("/");
  await expect(page.getByRole("region", { name: "모델별 최신 상태" })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "성능 추세" })).toBeVisible();
  await expect(page.getByRole("group", { name: "조회 기간" })).toBeVisible();
});

test("an empty short time window can be expanded without reloading the page", async ({ page }) => {
  const data = await mockApi(page);
  await page.route("**/api/auto-probe/trend*", (route) => {
    const hours = Number(new URL(route.request().url()).searchParams.get("hours"));
    return route.fulfill({ json: hours < 1 ? [] : data.trend });
  });
  await page.goto("/?hours=0.08333333333333333");
  const ranges = page.getByRole("group", { name: "조회 기간" });
  await expect(ranges).toBeVisible();
  await ranges.getByRole("button", { name: "1시간", exact: true }).click();
  await expect(page.locator(".recharts-wrapper").first()).toBeVisible();
});

test("mobile navigation and dashboard controls fit the viewport in both themes", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockApi(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "모델 모니터링", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "모델별 최신 상태" })).toBeVisible();
  await expect(page.locator(".recharts-wrapper").first()).toBeVisible();
  for (const theme of ["dark", "light"]) {
    await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
});

test("a failed catalog still accounts for channels declared by the collector", async ({ page }) => {
  const fixture = await mockApi(page);
  await page.route("**/api/models", (route) => route.fulfill({ status: 503, body: "{}" }));
  await page.route("**/api/auto-probe/latest*", (route) => route.fulfill({ json: fixture.latest.slice(0, 1) }));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "모니터링 채널 6", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "확인 필요 5", exact: true })).toBeVisible();
});

test("coverage is unknown when both the catalog and expected count are unavailable", async ({ page }) => {
  const fixture = await mockApi(page);
  await page.route("**/api/models", (route) => route.fulfill({ status: 503, body: "{}" }));
  await page.route("**/api/auto-probe/latest*", (route) => route.fulfill({ json: fixture.latest.slice(0, 1) }));
  await page.route("**/api/auto-probe/status", (route) => route.fulfill({ json: { ...fixture.status, expected_model_count: undefined } }));
  await page.goto("/");
  await expect(page.getByRole("button", { name: "모니터링 채널 —", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "확인 필요 —", exact: true })).toBeVisible();
});

test("isolated successful measurements remain visible in dense charts", async ({ page }) => {
  const fixture = await mockApi(page);
  const data = Array.from({ length: 280 }, (_, index) => fixture.latest.slice(0, 3).map((row, model) => ({
    ...row, timestamp: new Date(Date.now() - index * 60_000).toISOString(),
    status: model === 0 && index % 2 ? "error" : "success",
    ttft_ms: model === 0 && index % 2 ? null : 200 + model * 100,
  }))).flat();
  await page.route("**/api/auto-probe/trend*", (route) => route.fulfill({ json: data }));
  await page.goto("/?hours=6");
  const chart = page.getByRole("figure", { name: "TTFT 추이", exact: true });
  await expect(chart.locator(".recharts-line").first().locator("circle")).toHaveCount(140);
});

test("a paused display does not keep an expired running cycle marked active", async ({ page }) => {
  const fixture = await mockApi(page);
  await page.clock.install({ time: new Date() });
  await page.route("**/api/auto-probe/status", (route) => route.fulfill({
    json: { ...fixture.status, cycle_state: "running", current_cycle_running: true, running_timeout_seconds: 900 },
  }));
  await page.goto("/");
  const status = page.getByRole("region", { name: "자동 프로빙 상태" });
  await expect(status).toContainText("프로빙 진행 중");
  await status.getByRole("checkbox").uncheck();
  await page.clock.fastForward(16 * 60_000);
  await expect(status).toContainText("수집 지연");
});

test("graded card values wrap before the marker instead of overflowing their column at 320px", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  const fixture = await mockApi(page);
  // chat-short 기준: TTFT 12345ms → 위험, 총 12.0s → 위험, TPS 15.0 → 경고 (가장 긴 "15.0 tok/s ▲")
  const latest = fixture.latest.map((row, index) => index === 0 ? { ...row, ttft_ms: 12_345, total_latency_ms: 12_000, tps: 15 } : row);
  await page.route("**/api/auto-probe/latest*", (route) => route.fulfill({ json: latest }));
  await page.goto("/");
  const models = page.getByRole("region", { name: "모델별 최신 상태" });
  const values = models.getByRole("article").filter({ hasText: modelCatalog[0].name }).locator("[data-grade]");
  await expect(values).toHaveCount(3);
  expect(await values.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-grade")))).toEqual(["critical", "critical", "warning"]);
  await expect(values.nth(2)).toHaveText(/^15\.0\s*tok\/s\s*▲$/);
  const boxes = await values.evaluateAll((nodes) => nodes.map((node) => {
    const column = node.parentElement!.getBoundingClientRect();
    const parts = Array.from(node.children).map((child) => child.getBoundingClientRect());
    return { left: column.left, right: column.right, overflow: node.scrollWidth > node.clientWidth, partsRight: Math.max(...parts.map((part) => part.right)) };
  }));
  for (const [index, box] of boxes.entries()) {
    expect(box.overflow).toBe(false);
    expect(box.partsRight).toBeLessThanOrEqual(box.right + 0.5);
    if (index + 1 < boxes.length) expect(box.partsRight).toBeLessThan(boxes[index + 1].left);
  }
  const marker = values.nth(2).locator("[data-marker]");
  await expect(marker).toHaveText("▲");
  expect(await marker.evaluate((node) => getComputedStyle(node).fontSize)).toBe("12px");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("card metric values are graded per workload category with a non-color cue in both themes", async ({ page }) => {
  const fixture = await mockApi(page);
  // chat-short 기준: TTFT 3200ms → 경고(≥3000), 총 12s → 위험(≥10000), TPS 12 → 위험(<15)
  const latest = fixture.latest.map((row, index) => index === 0 ? { ...row, ttft_ms: 3200, total_latency_ms: 12_000, tps: 12 } : row);
  await page.route("**/api/auto-probe/latest*", (route) => route.fulfill({ json: latest }));
  await page.goto("/");
  const models = page.getByRole("region", { name: "모델별 최신 상태" });
  const slow = models.getByRole("article").filter({ hasText: modelCatalog[0].name });
  const values = slow.locator("[data-grade]");
  await expect(values).toHaveCount(3);
  expect(await values.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-grade")))).toEqual(["warning", "critical", "critical"]);
  await expect(values.first()).toHaveAttribute("title", "경고 — 짧은 대화 기준 TTFT 3초 이상, 위험 8초 이상");
  await expect(slow.getByRole("button").first()).toHaveAccessibleDescription(/TTFT 3200 ms, 경고 — 짧은 대화 기준.*TPS 12\.0 tok\/s, 위험/);
  await expect(values.first()).toContainText("▲");
  await expect(values.nth(1)).toContainText("◆");

  const healthy = models.getByRole("article").filter({ hasText: modelCatalog[3].name }).locator("[data-grade]");
  expect(await healthy.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-grade")))).toEqual(["normal", "normal", "normal"]);
  // KO 등급 이름 "양호"는 채널 건강 배지 "정상"과 다른 단어 — 한 카드에 "✓ 정상"과 ◆ 위험이 같은 단어로 겹치지 않게.
  await expect(healthy.first()).toHaveAttribute("title", /^양호 — /);
  const legend = models.locator("summary").filter({ hasText: "기준값 보기" });
  await expect(legend.getByText("지표 등급:", { exact: true })).toBeVisible();
  await expect(legend).toContainText(/지표 등급:.*양호.*경고.*위험.*워크로드 카테고리별 기준/);
  await expect(legend).not.toContainText("정상");
  // 양호 값에는 표지가 없으므로 범례도 양호는 모양 없는 색 견본만 — ●처럼 값 표지로 오해할 글자는 없다.
  await expect(legend.locator('[data-swatch="normal"]')).toBeVisible();
  await expect(legend).not.toContainText("●");
  await expect(healthy.first().locator("[data-marker]")).toHaveCount(0);
  await expect(models.getByRole("article").filter({ hasText: modelCatalog[1].name }).locator("[data-grade]")).toHaveCount(0);

  const colors = async () => [values.first(), values.nth(1), healthy.first()].reduce<Promise<string[]>>(
    async (acc, locator) => [...await acc, await locator.evaluate((node) => getComputedStyle(node).color)], Promise.resolve([]));
  expect(await colors()).toEqual(["rgb(252, 211, 77)", "rgb(251, 113, 133)", "rgb(147, 197, 253)"]);
  await page.evaluate(() => document.documentElement.classList.add("light"));
  expect(await colors()).toEqual(["rgb(180, 83, 9)", "rgb(190, 18, 60)", "rgb(29, 78, 216)"]);

  await models.getByText("기준값 보기", { exact: true }).click();
  await expect(models.getByRole("row", { name: /짧은 대화/ })).toContainText("3초");
  await expect(models.getByRole("row", { name: /카테고리 미지정/ })).toContainText("24초");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

const cadenceCatalog = [
  { id: "anthropic:claude-sonnet-5", name: "Anthropic Claude Sonnet 5 (US)" },
  { id: "global.anthropic.claude-sonnet-5", name: "Bedrock Claude Sonnet 5 (Global)" },
];

/** Both channels last measured 12 minutes ago: past a 5-minute channel's 5 min + grace, inside 10 min + grace. */
async function mockCadenceCards(page: Page) {
  const fixture = await mockApi(page);
  const now = Date.now();
  const latest = cadenceCatalog.map((model, index) => ({
    ...fixture.latest[0], id: index + 1, model_id: model.id, model_name: model.name,
    timestamp: new Date(now - 12 * 60_000).toISOString(),
  }));
  await page.route("**/api/models", (route) => route.fulfill({ json: cadenceCatalog }));
  await page.route("**/api/auto-probe/latest*", (route) => route.fulfill({ json: latest }));
  return fixture;
}

function cardBadge(page: Page, index: number, badge: string) {
  return page.getByRole("region", { name: "모델별 최신 상태" }).getByRole("article")
    .filter({ hasText: cadenceCatalog[index].name }).getByText(badge, { exact: true });
}

/**
 * Navigate and wait until the dashboard has rendered /status. The cadence text, the stale badges and the
 * workload interval all have fallbacks that hold without /status, so a negative assertion made before this
 * would pass even if a note were shown once /status lands. The last-probe age comes only from /status ("—" before).
 */
async function gotoWithStatus(page: Page, url: string) {
  const statusResponse = page.waitForResponse("**/api/auto-probe/status");
  await page.goto(url);
  await statusResponse;
  await expect(page.getByRole("region", { name: "자동 프로빙 상태" })).toContainText(/마지막 프로빙: \d+분 전/);
}

test("by default Claude Platform on AWS follows the base 5-minute cadence and gets no separate note (v2.29.1)", async ({ page }) => {
  const fixture = await mockCadenceCards(page);
  await page.route("**/api/auto-probe/status", (route) => route.fulfill({
    json: { ...fixture.status, expected_model_count: 2, category_interval_seconds: 1800,
      channel_intervals: { anthropic: 300 }, channel_category_intervals: { anthropic: 1800 } },
  }));
  await gotoWithStatus(page, "/");
  const status = page.getByRole("region", { name: "자동 프로빙 상태" });
  await expect(status).toContainText("5분 주기");
  await expect(cardBadge(page, 0, "수집 지연")).toBeVisible();
  await expect(cardBadge(page, 1, "수집 지연")).toBeVisible();
  await expect(status).not.toContainText("Claude Platform on AWS");

  await gotoWithStatus(page, "/?category=reasoning");
  await expect(page.getByRole("region", { name: "워크로드" })).toContainText("선택한 워크로드는 약 30분마다 수집됩니다.");
  await expect(page.getByRole("region", { name: "워크로드" })).not.toContainText("Claude Platform on AWS");
});

test("until /status answers every channel uses the base cadence, then /status overrides take effect", async ({ page }) => {
  const fixture = await mockCadenceCards(page);
  let releaseStatus = () => {};
  const statusHeld = new Promise<void>((resolve) => { releaseStatus = resolve; });
  await page.route("**/api/auto-probe/status", async (route) => {
    await statusHeld;
    await route.fulfill({ json: { ...fixture.status, expected_model_count: 2,
      channel_intervals: { anthropic: 600 }, channel_category_intervals: { anthropic: 3600 } } });
  });
  await page.goto("/");
  // No CP override is assumed before /status (v2.29.1): the 12-minute-old CP card is stale like Bedrock.
  await expect(cardBadge(page, 0, "수집 지연")).toBeVisible();
  await expect(cardBadge(page, 1, "수집 지연")).toBeVisible();
  releaseStatus();
  await expect(cardBadge(page, 0, "정상")).toBeVisible();
  await expect(cardBadge(page, 1, "수집 지연")).toBeVisible();
});

test("with the 10-minute knob (/status anthropic 600) Claude Platform on AWS is not flagged stale", async ({ page }) => {
  const fixture = await mockCadenceCards(page);
  await page.route("**/api/auto-probe/status", (route) => route.fulfill({
    json: { ...fixture.status, expected_model_count: 2, category_interval_seconds: 1800,
      channel_intervals: { anthropic: 600 }, channel_category_intervals: { anthropic: 3600 } },
  }));
  await page.goto("/");
  const status = page.getByRole("region", { name: "자동 프로빙 상태" });
  await expect(status).toContainText("5분 주기");
  await expect(status).toContainText("Claude Platform on AWS 10분 주기");
  await expect(cardBadge(page, 0, "정상")).toBeVisible();
  await expect(cardBadge(page, 1, "수집 지연")).toBeVisible();

  await page.goto("/?category=reasoning");
  await expect(page.getByRole("region", { name: "워크로드" })).toContainText(
    "선택한 워크로드는 약 30분마다 수집됩니다. Claude Platform on AWS 채널은 약 60분마다 수집됩니다.");
});
