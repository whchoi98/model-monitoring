import { expect, test } from "@playwright/test";
import { mockApi, modelCatalog } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("named attention channels lead to their current result without losing the query scope", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/?hours=6&category=reasoning");
  const attention = page.getByRole("region", { name: "확인이 필요한 채널", exact: true });
  await expect(attention).toBeVisible();
  await expect(attention.getByRole("button", { name: /상태 보기$/ })).toHaveCount(4);
  await expect(attention).toContainText(modelCatalog[1].name);
  await expect(attention).not.toContainText(modelCatalog[0].name);
  for (const [index, health] of [[1, "오류"], [2, "과부하"], [4, "수집 지연"], [5, "미수집"]] as const) {
    await expect(attention.getByRole("button", { name: `${modelCatalog[index].name} 상태 보기`, exact: true })).toHaveAccessibleDescription(health);
  }
  await attention.getByRole("button", { name: `${modelCatalog[1].name} 상태 보기`, exact: true }).click();

  const models = page.getByRole("region", { name: "모델별 최신 상태", exact: true });
  await expect(models.getByRole("article")).toHaveCount(1);
  await expect(models.getByRole("article")).toContainText(modelCatalog[1].name);
  await expect(models.getByRole("heading", { name: "모델별 최신 상태", exact: true })).toBeFocused();
  const query = new URL(page.url()).searchParams;
  expect(query.get("hours")).toBe("6");
  expect(query.get("category")).toBe("reasoning");
  expect(query.get("q")).toBe(modelCatalog[1].name);
});

test("compact and card views preserve selected models and survive a reload", async ({ page }) => {
  await page.goto("/?hours=6&category=reasoning");
  const models = page.getByRole("region", { name: "모델별 최신 상태", exact: true });
  const view = models.getByRole("group", { name: "목록 보기", exact: true });
  await expect(view.getByRole("button", { name: "간결하게", exact: true })).toHaveAttribute("aria-pressed", "true");
  const card = models.getByRole("article").filter({ hasText: modelCatalog[0].name });
  const select = card.getByRole("button", { name: `${modelCatalog[0].name} 추세 비교 선택`, exact: true });
  await select.click();
  const compactHeight = (await card.boundingBox())!.height;

  await view.getByRole("button", { name: "카드로", exact: true }).click();
  await expect(card.getByText(modelCatalog[0].id, { exact: true })).toBeVisible();
  expect((await card.boundingBox())!.height).toBeGreaterThan(compactHeight);
  await page.reload();
  await expect(view.getByRole("button", { name: "카드로", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(select).toHaveAttribute("aria-pressed", "true");
  const query = new URL(page.url()).searchParams;
  expect(query.get("layout")).toBe("cards");
  expect(query.get("hours")).toBe("6");
  expect(query.get("category")).toBe("reasoning");
  expect(query.get("models")).toBe(modelCatalog[0].name);

  await view.getByRole("button", { name: "간결하게", exact: true }).click();
  await expect(select).toHaveAttribute("aria-pressed", "true");
  await expect(models.getByRole("article")).toHaveCount(6);
});

test("collapsing a family keeps its comparison selection and searching reveals matching rows", async ({ page }) => {
  await page.goto("/");
  const models = page.getByRole("region", { name: "모델별 최신 상태", exact: true });
  await models.getByRole("button", { name: `${modelCatalog[0].name} 추세 비교 선택`, exact: true }).click();
  const family = models.getByRole("button", { name: "Claude Fable 5.1 채널", exact: true });
  await expect(family).toHaveAttribute("aria-expanded", "true");
  await family.click();
  await expect(family).toHaveAttribute("aria-expanded", "false");
  await expect(models.getByRole("button", { name: `${modelCatalog[0].name} 추세 비교 선택`, exact: true })).toBeHidden();
  const dock = page.getByRole("region", { name: "선택한 모델 비교", exact: true });
  await expect(dock).toContainText(modelCatalog[0].name);

  await models.getByRole("searchbox", { name: "모델 검색", exact: true }).fill("Fable");
  await expect(models.getByRole("article")).toHaveCount(3);
  await expect(models.getByRole("button", { name: `${modelCatalog[0].name} 추세 비교 선택`, exact: true })).toHaveAttribute("aria-pressed", "true");
});

test("mobile comparison controls remain reachable, avoid the chat button and restore focus when cleared", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  const models = page.getByRole("region", { name: "모델별 최신 상태", exact: true });
  await models.getByRole("button", { name: `${modelCatalog[0].name} 추세 비교 선택`, exact: true }).click();
  const dock = page.getByRole("region", { name: "선택한 모델 비교", exact: true });
  await expect(dock).toContainText(modelCatalog[0].name);
  await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
  const box = (await dock.boundingBox())!;
  const fab = (await page.locator("[data-chat-fab]").boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(0);
  expect(box.y + box.height).toBeLessThanOrEqual(844);
  expect(box.x + box.width).toBeLessThanOrEqual(fab.x);
  await expect.poll(() => page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).scrollPaddingBottom))).toBeGreaterThan(box.height);
  await dock.getByRole("button", { name: "성능 추세로 이동", exact: true }).click();
  await expect(page.getByRole("heading", { name: "성능 추세", exact: true })).toBeFocused();
  await dock.getByRole("button", { name: "선택 해제", exact: true }).click();
  await expect(dock).toBeHidden();
  await expect(page.locator("html")).toHaveCSS("scroll-padding-bottom", "0px");
  await expect(models.getByRole("heading", { name: "모델별 최신 상태", exact: true })).toBeFocused();
  expect(new URL(page.url()).searchParams.get("models")).toBe("all");
});

test("family presets compare only their channels and preserve the period and workload", async ({ page }) => {
  await page.goto("/?hours=6&category=reasoning");
  const trends = page.getByRole("region", { name: "성능 추세", exact: true });
  await trends.getByRole("combobox", { name: "계열별 비교", exact: true }).selectOption("Claude Fable 5.1");
  const query = new URL(page.url()).searchParams;
  expect(query.get("models")?.split(",").sort()).toEqual([
    "Anthropic Claude Fable 5.1 (US)",
    "Bedrock Claude Fable 5.1 (Global)",
    "Bedrock Claude Fable 5.1 (US)",
  ]);
  expect(query.get("hours")).toBe("6");
  expect(query.get("category")).toBe("reasoning");
  await expect(trends.getByRole("figure", { name: "TTFT 추이", exact: true }).locator(".recharts-line")).toHaveCount(3);
  await page.reload();
  await expect(trends.getByRole("combobox", { name: "계열별 비교", exact: true })).toHaveValue("Claude Fable 5.1");
  await trends.getByRole("group", { name: "비교 범위", exact: true }).getByRole("button", { name: "대표 모델", exact: true }).click();
  await expect(trends.getByRole("figure", { name: "TTFT 추이", exact: true }).locator(".recharts-line")).toHaveCount(2);
  await trends.getByRole("group", { name: "비교 범위", exact: true }).getByRole("button", { name: "전체", exact: true }).click();
  expect(new URL(page.url()).searchParams.get("models")).toBe("all");
  await expect(trends.getByRole("figure", { name: "TTFT 추이", exact: true }).locator(".recharts-line")).toHaveCount(5);
});

test("Tab traversal keeps focused model and trend controls above the comparison dock", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("region", { name: "모델별 최신 상태", exact: true })
    .getByRole("button", { name: `${modelCatalog[0].name} 추세 비교 선택`, exact: true }).click();
  await expect(page.getByRole("region", { name: "선택한 모델 비교", exact: true })).toBeVisible();
  for (let index = 0; index < 20; index++) {
    await page.keyboard.press("Tab");
    await expect.poll(() => page.evaluate(() => {
      const focused = document.activeElement;
      if (!(focused instanceof HTMLElement)) return false;
      const rect = focused.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
      return hit !== null && focused.contains(hit);
    }), { message: "Keyboard focus must remain visible above fixed controls" }).toBe(true);
  }
});

test("navigation groups expose their destinations while unit prices stay next to the dashboard", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "메뉴 열기", exact: true }).click();
  const nav = page.getByRole("navigation", { name: "모바일 메뉴", exact: true });
  await expect(nav.getByRole("group", { name: "탐색·검증", exact: true }).getByRole("link", { name: "GPT on AWS", exact: true })).toBeVisible();
  await expect(nav.getByRole("group", { name: "분석", exact: true }).getByRole("link", { name: "신뢰성", exact: true })).toBeVisible();
  const links = nav.getByRole("link");
  await expect(links.nth(0)).toHaveAttribute("href", "/");
  await expect(links.nth(1)).toHaveAttribute("href", "/pricing");
  await nav.getByRole("group", { name: "분석", exact: true }).getByRole("link", { name: "신뢰성", exact: true }).click();
  await expect(page).toHaveURL(/\/reliability$/);
  await expect(page.getByRole("button", { name: "메뉴 열기", exact: true })).toHaveAttribute("aria-expanded", "false");
});
