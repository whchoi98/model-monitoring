import { expect, test } from "@playwright/test";
import { mockApi } from "./fixtures";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const claudeFamilies = ["Fable 5.1", "Fable 5", "Opus 5", "Opus 4.8", "Opus 4.7", "Opus 4.6", "Sonnet 5", "Sonnet 4.6", "Haiku 4.5"];
const modelNames = [
  ...claudeFamilies.flatMap((family) => [
    `Bedrock Claude ${family} (Global)`, `Bedrock Claude ${family} (US)`,
    ...(family === "Opus 4.6" ? [] : [`Anthropic Claude ${family} (US)`]),
  ]),
  "Bedrock Nova 2.0 Lite (US)",
  ...([
    ["6 Astra", ["Global", "US", "us-west-2"]],
    ["5.6 Sol", ["Global", "us-east-1", "us-east-2"]],
    ["5.6 Terra", ["Global", "us-east-1", "us-east-2", "us-west-2"]],
    ["5.6 Luna", ["Global", "us-east-1", "us-east-2", "us-west-2"]],
    ["5.5", ["us-east-1", "us-east-2"]],
    ["5.4", ["us-east-1", "us-east-2", "us-west-2"]],
  ] as const).flatMap(([family, regions]) => regions.map((region) => `OpenAI GPT ${family} (${region})`)),
];

for (const [width, lang, theme] of [[1440, "ko", "dark"], [1440, "en", "light"], [390, "ko", "dark"], [390, "en", "light"]] as const) {
  test(`46-channel dashboard is usable at ${width}px in ${lang}/${theme}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width < 768 ? 844 : 1100 });
    await page.addInitScript(({ lang, theme }) => {
      localStorage.setItem("lang", lang);
      localStorage.setItem("theme", theme);
    }, { lang, theme });
    const fixture = await mockApi(page);
    const models = modelNames.map((name, index) => ({ id: `fixture-channel-${index}`, name }));
    const latest = models.slice(0, -1).map((model, index) => ({
      ...fixture.latest[0], model_id: model.id, model_name: model.name,
      status: index === 2 ? "error" : index === 9 ? "overloaded" : "success",
      timestamp: new Date(Date.now() - (index === 12 ? 45 : 2) * 60_000).toISOString(),
      ttft_ms: index === 2 || index === 9 ? null : 120 + index * 35,
      tps: 35 + index * 1.6,
      error_message: index === 2 ? "ServiceUnavailable: the model could not serve this request." : index === 9 ? "Vendor overloaded" : null,
    }));
    const trend = Array.from({ length: 6 }, (_, sample) => latest.map((row) => ({
      ...row, timestamp: new Date(Date.now() - (2 + 5 * sample) * 60_000).toISOString(),
      ttft_ms: row.ttft_ms == null ? null : row.ttft_ms + sample * 12,
    }))).flat();
    await page.route("**/api/models", (route) => route.fulfill({ json: models }));
    await page.route("**/api/auto-probe/latest*", (route) => route.fulfill({ json: latest }));
    await page.route("**/api/auto-probe/trend*", (route) => route.fulfill({ json: trend }));
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto("/");
    const region = page.getByRole("region", { name: lang === "ko" ? "모델별 최신 상태" : "Latest Model Status" });
    await expect(region.getByRole("article")).toHaveCount(46);
    await expect(page.locator(".recharts-wrapper")).toHaveCount(3);
    if (width < 768) {
      const attention = await page.getByRole("button", { name: lang === "ko" ? "확인 필요 4" : "Needs attention 4", exact: true }).boundingBox();
      expect(attention).not.toBeNull();
      expect(attention!.y + attention!.height).toBeLessThanOrEqual(844);
    }
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expect(page.locator("html")).toHaveAttribute("lang", lang);
    await page.evaluate(() => document.fonts.ready);
    const directory = path.resolve(process.cwd(), "../screenshots");
    await mkdir(directory, { recursive: true });
    await page.screenshot({ path: path.join(directory, `monitoring-${width}-${lang}-${theme}-${testInfo.project.name}.png`) });
    expect(errors).toEqual([]);
  });
}

test("Korean composition Enter does not send an unfinished chat message", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("auth_token", "fixture-token");
    localStorage.setItem("lang", "en");
  });
  await page.route("**/api/auth/me", (route) => route.fulfill({ json: { id: 1, username: "fixture-user" } }));
  let sent = 0;
  await page.route("**/api/chat/stream", (route) => {
    sent += 1;
    return route.fulfill({ contentType: "text/event-stream", body: 'event: final\ndata: {"ok":true}\n\n' });
  });
  await page.goto("/chat");
  const input = page.getByRole("textbox", { name: "Message", exact: true });
  await input.fill("모델 상태");
  await input.dispatchEvent("keydown", { key: "Enter", code: "Enter", isComposing: true, bubbles: true });
  await expect(input).toHaveValue("모델 상태");
  expect(sent).toBe(0);
  await input.press("Enter");
  await expect.poll(() => sent).toBe(1);
});
