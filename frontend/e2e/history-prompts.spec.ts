import { expect, test, type Page, type Request } from "@playwright/test";
import type { ModelStats, PromptSet } from "../src/lib/types";
import { mockApi } from "./fixtures";

const MODEL = "OpenAI GPT 6 Astra (us-west-2)";
const PROMPT_NAME = "Quarterly report <draft>";

function stats(name = MODEL): ModelStats {
  return {
    model_id: name, model_name: name, count: 2,
    avg_ttft_ms: 0, p50_ttft_ms: null, p95_ttft_ms: 250, p99_ttft_ms: null,
    avg_latency_ms: 1500, p50_latency_ms: null, p95_latency_ms: 2000, p99_latency_ms: null,
    avg_tps: 0, p50_tps: null, p95_tps: 40, p99_tps: null,
    avg_server_latency_ms: null, p50_server_latency_ms: null,
    p95_server_latency_ms: null, p99_server_latency_ms: null,
  };
}

function promptSet(id: number, name: string): PromptSet {
  return { id, name, prompts: ["Summarize the report."], temperature: 0.1, max_tokens: 256 };
}

function signal() {
  let resolve!: () => void;
  const promise = new Promise<void>((done) => { resolve = done; });
  return { promise, resolve };
}

function watchNativeDialogs(page: Page) {
  const types: string[] = [];
  page.on("dialog", async (dialog) => {
    types.push(dialog.type());
    await dialog.dismiss();
  });
  return types;
}

async function promptApi(page: Page, initial = [promptSet(7, PROMPT_NAME), promptSet(8, "Keep this prompt")]) {
  const state = {
    sets: [...initial],
    readError: false,
    createError: false,
    deleteError: false,
    deleteGate: null as Promise<void> | null,
    onDelete: () => {},
    writes: [] as { method: string; id?: number; body?: unknown; auth?: string }[],
  };
  await page.route("**/api/prompts**", async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/prompts" && request.method() === "GET") {
      return route.fulfill(state.readError
        ? { status: 503, json: { detail: "Fixture read failure" } }
        : { json: state.sets });
    }
    if (pathname === "/api/prompts" && request.method() === "POST") {
      const body = request.postDataJSON() as Omit<PromptSet, "id">;
      state.writes.push({ method: "POST", body, auth: request.headers().authorization });
      if (state.createError) return route.fulfill({ status: 503, json: { detail: "Fixture create failure" } });
      const created = { ...body, id: 99 };
      state.sets = [...state.sets, created];
      return route.fulfill({ status: 201, json: created });
    }
    if (/^\/api\/prompts\/\d+$/.test(pathname) && request.method() === "DELETE") {
      const id = Number(pathname.split("/").pop());
      state.writes.push({ method: "DELETE", id, auth: request.headers().authorization });
      state.onDelete();
      if (state.deleteGate) await state.deleteGate;
      if (state.deleteError) return route.fulfill({ status: 503, json: { detail: "Fixture delete failure" } });
      state.sets = state.sets.filter((item) => item.id !== id);
      return route.fulfill({ status: 204 });
    }
    return route.fallback();
  });
  return state;
}

test.beforeEach(async ({ page }) => {
  // Only explicit API fixtures may handle mutations; block external telemetry
  // or other ambient requests if the local dev server has deployment settings.
  await page.route("**/*", (route) => {
    const request = route.request();
    const local = ["127.0.0.1", "localhost"].includes(new URL(request.url()).hostname);
    return local && ["GET", "HEAD"].includes(request.method()) ? route.fallback() : route.abort();
  });
  // The catch-all fixture fulfills every API request, including unknown writes.
  await mockApi(page);
  await page.addInitScript(() => {
    if (!localStorage.getItem("lang")) localStorage.setItem("lang", "en");
    localStorage.setItem("auth_token", "history-prompts-fixture-token");
  });
  await page.route("**/api/auth/me", (route) => route.fulfill({ json: { id: 1, username: "workflow-user" } }));
});

test("history fetches only while open, keeps background inert, and Escape returns focus", async ({ page }) => {
  let reads = 0;
  await page.route("**/api/results/stats?*", (route) => {
    reads += 1;
    return route.fulfill({ json: { models: [stats()] } });
  });
  await page.goto("/");
  const opener = page.getByRole("button", { name: "History", exact: true });
  await expect(page.getByRole("heading", { name: "Model monitoring", exact: true })).toBeVisible();
  expect(reads).toBe(0);
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Historical Stats", exact: true });
  await expect(dialog.getByRole("heading", { name: MODEL, exact: true })).toBeVisible();
  expect(reads).toBeGreaterThan(0);
  await dialog.getByRole("button").last().focus();
  await page.keyboard.press("Tab");
  // Chromium may visit browser chrome at the native dialog boundary. It must
  // return to the modal, never to an interactive control behind the dialog.
  if (!await page.evaluate(() => document.hasFocus())) await page.keyboard.press("Tab");
  await expect.poll(() => dialog.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
});

test("history errors are distinct from an empty successful response and offer retry", async ({ page }) => {
  let fail = true;
  await page.route("**/api/results/stats?*", (route) => route.fulfill(fail
    ? { status: 503, json: { detail: "Unavailable" } }
    : { json: { models: [] } }));
  await page.goto("/");
  await page.getByRole("button", { name: "History", exact: true }).click();
  const error = page.getByRole("alert").filter({ hasText: "Historical Stats" });
  await expect(error).toBeVisible();
  await expect(page.getByText("No historical data available for this time range.", { exact: true })).toHaveCount(0);
  fail = false;
  await error.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(error).toHaveCount(0);
  await expect(page.getByText("No historical data available for this time range.", { exact: true })).toBeVisible();
});

test("history discards a late period response and retains same-period data after refresh failure", async ({ page }) => {
  const now = new Date();
  await page.clock.setFixedTime(now);
  const started = signal();
  const release = signal();
  const settled = signal();
  let held: Request | undefined;
  let fail = false;
  const onSettled = (request: Request) => { if (request === held) settled.resolve(); };
  page.on("requestfinished", onSettled);
  page.on("requestfailed", onSettled);
  await page.route("**/api/results/stats?*", async (route) => {
    const start = new URL(route.request().url()).searchParams.get("start_time")!;
    const hours = Math.round((now.getTime() - Date.parse(start)) / 3_600_000);
    if (hours === 6) {
      held = route.request();
      started.resolve();
      await release.promise;
      return route.fulfill({ json: { models: [stats("Older six-hour sample")] } });
    }
    return route.fulfill(fail
      ? { status: 503, json: { detail: "Unavailable" } }
      : { json: { models: [stats(hours === 1 ? "Latest hourly sample" : MODEL)] } });
  });
  try {
    await page.goto("/");
    await page.getByRole("button", { name: "History", exact: true }).click();
    await expect(page.getByRole("heading", { name: MODEL, exact: true })).toBeVisible();
    await page.getByRole("button", { name: "6 Hours", exact: true }).click();
    await started.promise;
    await expect(page.getByRole("heading", { name: MODEL, exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "1 Hour", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Latest hourly sample", exact: true })).toBeVisible();
    release.resolve();
    await settled.promise;
    await page.evaluate(() => new Promise<void>((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
    await expect(page.getByRole("heading", { name: "Latest hourly sample", exact: true })).toBeVisible();
    await expect(page.getByText("Older six-hour sample", { exact: true })).toHaveCount(0);
    const dialog = page.getByRole("dialog", { name: "Historical Stats", exact: true });
    const checkedAt = await dialog.getByText(/^Last checked:/).textContent();
    fail = true;
    await dialog.getByRole("button", { name: "Refresh", exact: true }).click();
    await expect(dialog.getByRole("alert")).toContainText("Showing the last successful result.");
    await expect(dialog.getByRole("heading", { name: "Latest hourly sample", exact: true })).toBeVisible();
    await expect(dialog.getByText(/^Last checked:/)).toHaveText(checkedAt!);
  } finally {
    release.resolve();
  }
});

for (const lang of ["en", "ko"] as const) {
  test(`history metrics and filters fit mobile in ${lang} without inventing values or channels`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript((value) => localStorage.setItem("lang", value), lang);
    await page.route("**/api/results/stats?*", (route) => route.fulfill({ json: { models: [stats()] } }));
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("lang", lang);
    await page.locator("header button[aria-controls]").click();
    await page.getByRole("button", { name: lang === "en" ? "History" : "이력 조회", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: lang === "en" ? "Historical Stats" : "이력 통계", exact: true });
    const card = dialog.getByRole("article", { name: MODEL, exact: true });
    await expect(card.getByRole("group", { name: "TTFT", exact: true })).toContainText("0 ms");
    await expect(card.getByRole("group", { name: "TTFT", exact: true })).toContainText("—");
    await expect(card.getByRole("group", { name: "Latency", exact: true })).toContainText("1500 ms");
    await expect(card.getByRole("group", { name: "TPS", exact: true })).toContainText("0.0 tok/s");
    await expect(card.getByText("us-west-2", { exact: true })).toBeVisible();
    const ranges = dialog.getByRole("group", { name: lang === "en" ? "Time range" : "조회 기간", exact: true });
    await expect(ranges.locator("button[aria-pressed='true']")).toHaveCount(1);
    const first = await ranges.getByRole("button").first().boundingBox();
    const last = await ranges.getByRole("button").last().boundingBox();
    expect(last!.y).toBeGreaterThan(first!.y);
    const modelFilter = dialog.getByRole("button", { name: MODEL, exact: true });
    await modelFilter.click();
    await expect(modelFilter).toHaveAttribute("aria-pressed", "true");
    await ranges.getByRole("button", { name: lang === "en" ? "1 Hour" : "1시간", exact: true }).click();
    await expect(modelFilter).toHaveAttribute("aria-pressed", "true");
    for (const theme of ["dark", "light"]) {
      await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
      await expect.poll(() => dialog.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
  });
}

test("prompt-list failure leaves the create form usable and retry can report a genuine empty list", async ({ page }) => {
  const api = await promptApi(page, []);
  api.readError = true;
  await page.goto("/prompts");
  await expect(page.getByPlaceholder("Name", { exact: true })).toBeEnabled();
  const error = page.getByRole("alert").filter({ hasText: "saved prompt sets" });
  await expect(error).toBeVisible();
  await expect(page.getByText("No prompt sets saved yet.", { exact: true })).toHaveCount(0);
  api.readError = false;
  await error.getByRole("button", { name: "Retry", exact: true }).click();
  await expect(error).toHaveCount(0);
  await expect(page.getByText("No prompt sets saved yet.", { exact: true })).toBeVisible();
});

test("prompt creation reports errors inline, preserves input, and keeps a confirmed create after refresh failure", async ({ page }) => {
  const dialogs = watchNativeDialogs(page);
  const api = await promptApi(page);
  api.createError = true;
  await page.goto("/prompts");
  await page.getByPlaceholder("Name", { exact: true }).fill("  Release note  ");
  await page.getByPlaceholder("Prompt text", { exact: true }).fill("  Summarize this  ");
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Could not save" })).toBeVisible();
  await expect(page.getByPlaceholder("Name", { exact: true })).toHaveValue("  Release note  ");
  await expect(page.getByPlaceholder("Prompt text", { exact: true })).toHaveValue("  Summarize this  ");
  api.createError = false;
  api.readError = true;
  await page.getByRole("button", { name: "Save", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Created" })).toContainText("Release note");
  await expect(page.getByRole("heading", { name: "Release note", exact: true })).toBeVisible();
  await expect(page.getByRole("alert").filter({ hasText: "saved prompt sets" })).toBeVisible();
  await expect(page.getByPlaceholder("Name", { exact: true })).toHaveValue("");
  expect(api.writes).toHaveLength(2);
  expect(api.writes[1]).toEqual({
    method: "POST", auth: "Bearer history-prompts-fixture-token",
    body: { name: "Release note", prompts: ["Summarize this"], temperature: 0.1, max_tokens: 256 },
  });
  expect(dialogs).toEqual([]);
});

test("deletion confirmation names the exact prompt and cancel or Escape retains it", async ({ page }) => {
  const dialogs = watchNativeDialogs(page);
  const api = await promptApi(page);
  await page.goto("/prompts");
  const opener = page.getByRole("button", { name: `Delete ${PROMPT_NAME}`, exact: true });
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Delete prompt set", exact: true });
  await expect(dialog.getByText(PROMPT_NAME, { exact: true })).toBeVisible();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await opener.click();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
  await expect(page.getByRole("heading", { name: PROMPT_NAME, exact: true })).toBeVisible();
  expect(api.writes).toEqual([]);
  expect(dialogs).toEqual([]);
});

test("in-flight deletion cannot duplicate and a failed refresh cannot resurrect the deleted prompt", async ({ page }) => {
  const dialogs = watchNativeDialogs(page);
  const api = await promptApi(page);
  const started = signal();
  const release = signal();
  api.onDelete = started.resolve;
  api.deleteGate = release.promise;
  try {
    await page.goto("/prompts");
    await page.getByRole("button", { name: `Delete ${PROMPT_NAME}`, exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "Delete prompt set", exact: true });
    const confirm = dialog.getByRole("button", { name: /^Delet/ });
    await confirm.click();
    await started.promise;
    await expect(confirm).toBeDisabled();
    await confirm.dispatchEvent("click");
    expect(api.writes.filter((write) => write.method === "DELETE")).toHaveLength(1);
    api.readError = true;
    release.resolve();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByRole("status").filter({ hasText: "Deleted" })).toContainText(PROMPT_NAME);
    await expect(page.getByRole("heading", { name: PROMPT_NAME, exact: true })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Keep this prompt", exact: true })).toBeVisible();
    await expect(page.getByRole("alert").filter({ hasText: "saved prompt sets" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Saved prompt sets", exact: true })).toBeFocused();
    expect(api.writes).toEqual([{ method: "DELETE", id: 7, auth: "Bearer history-prompts-fixture-token" }]);
    expect(dialogs).toEqual([]);
  } finally {
    release.resolve();
  }
});

test("a failed deletion is announced inside the dialog and keeps the prompt available", async ({ page }) => {
  const api = await promptApi(page);
  api.deleteError = true;
  await page.goto("/prompts");
  await page.getByRole("button", { name: `Delete ${PROMPT_NAME}`, exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "Delete prompt set", exact: true });
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(dialog.getByRole("alert")).toContainText("Could not delete");
  await expect(dialog.getByRole("button", { name: "Delete", exact: true })).toBeEnabled();
  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(page.getByRole("heading", { name: PROMPT_NAME, exact: true })).toBeVisible();
  expect(api.writes.filter((write) => write.method === "DELETE")).toHaveLength(1);
});

test("deleting the last row of a long list restores focus to a visible list heading", async ({ page }) => {
  await promptApi(page, [
    ...Array.from({ length: 15 }, (_, index) => promptSet(100 + index, `Retained prompt ${index}`)),
    promptSet(7, PROMPT_NAME),
  ]);
  await page.goto("/prompts");
  const opener = page.getByRole("button", { name: `Delete ${PROMPT_NAME}`, exact: true });
  const heading = page.getByRole("heading", { name: "Saved prompt sets", exact: true });
  await opener.scrollIntoViewIfNeeded();
  await expect(heading).not.toBeInViewport();
  await opener.click();
  const dialog = page.getByRole("dialog", { name: "Delete prompt set", exact: true });
  await dialog.getByRole("button", { name: "Delete", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(heading).toBeFocused();
  await expect(heading).toBeInViewport();
});

test("optimizer failures are accessible and localized while retaining input and target", async ({ page }) => {
  await promptApi(page, []);
  await page.addInitScript(() => localStorage.setItem("lang", "ko"));
  let payload: unknown;
  await page.route("**/api/prompts/optimize", (route) => {
    payload = route.request().postDataJSON();
    return route.fulfill({ status: 503, json: { detail: "Fixture optimizer failure" } });
  });
  await page.goto("/prompts");
  const input = page.getByPlaceholder("최적화할 프롬프트를 입력하세요...", { exact: true });
  await input.fill("테스트 프롬프트");
  await page.getByRole("button", { name: "최적화", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "프롬프트를 최적화하지 못했습니다." })).toBeVisible();
  await expect(input).toHaveValue("테스트 프롬프트");
  expect(payload).toEqual({ prompt: "테스트 프롬프트", target_model_id: "global.anthropic.claude-fable-5-1" });
});

test("optimizer results still populate a new prompt set and a copy failure is announced", async ({ page }) => {
  await promptApi(page, []);
  await page.addInitScript(() => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: async () => { throw new DOMException("Fixture clipboard denial", "NotAllowedError"); } },
    });
  });
  const target = "us.anthropic.claude-sonnet-4-6";
  let payload: unknown;
  await page.route("**/api/prompts/optimize", (route) => {
    payload = route.request().postDataJSON();
    return route.fulfill({ json: {
      analyze_message: "Use a clear output format.",
      optimized_prompt: "Return a three-bullet summary.",
      target_model_id: target, request_id: "fixture-only",
    } });
  });
  await page.goto("/prompts");
  await page.getByLabel("Prompt to optimize", { exact: true }).fill("  Summarize the document.  ");
  await page.getByLabel("Target model", { exact: true }).selectOption(target);
  await page.getByRole("button", { name: "Optimize", exact: true }).click();
  await expect(page.getByText("Return a three-bullet summary.", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Copy", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Could not copy the prompt." })).toBeVisible();
  await page.getByRole("button", { name: "Use in new prompt set", exact: true }).click();
  await expect(page.getByLabel("Prompt text", { exact: true })).toHaveValue("Return a three-bullet summary.");
  await expect(page.getByLabel("Name", { exact: true })).toHaveValue(/^Optimized /);
  expect(payload).toEqual({ prompt: "Summarize the document.", target_model_id: target });
});

for (const lang of ["en", "ko"] as const) {
  test(`prompt controls fit mobile in ${lang} and both themes`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.addInitScript((value) => localStorage.setItem("lang", value), lang);
    await promptApi(page, [promptSet(7, `${PROMPT_NAME} ${"long-name".repeat(8)}`)]);
    await page.goto("/prompts");
    await expect(page.getByLabel(lang === "en" ? "Name" : "이름", { exact: true })).toBeEnabled();
    await expect(page.getByLabel(lang === "en" ? "Prompt text" : "프롬프트 내용", { exact: true })).toBeEnabled();
    for (const theme of ["dark", "light"]) {
      await page.evaluate((value) => document.documentElement.classList.toggle("light", value === "light"), theme);
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
  });
}
