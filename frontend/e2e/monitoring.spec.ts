import { test, expect } from "@playwright/test";
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
