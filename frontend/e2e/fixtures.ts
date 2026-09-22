import type { Page } from "@playwright/test";

export const modelCatalog = [
  { id: "anthropic-fable", name: "Anthropic Claude Fable 5.1 (US)" },
  { id: "global-fable", name: "Bedrock Claude Fable 5.1 (Global)" },
  { id: "us-fable", name: "Bedrock Claude Fable 5.1 (US)" },
  { id: "global-astra", name: "OpenAI GPT 6 Astra (Global)" },
  { id: "us-astra", name: "OpenAI GPT 6 Astra (US)" },
  { id: "regional-astra", name: "OpenAI GPT 6 Astra (us-west-2)" },
];

export function monitoringData() {
  const now = Date.now();
  const timestamp = (minutes: number) => new Date(now - minutes * 60_000).toISOString();
  const latest = modelCatalog.slice(0, 5).map((model, index) => ({
    id: index + 1, run_id: 42,
    model_id: model.id, model_name: model.name,
    timestamp: timestamp(index === 4 ? 45 : 2),
    status: index === 1 ? "error" : index === 2 ? "overloaded" : "success",
    ttft_ms: index === 1 || index === 2 ? null : 450 + index * 130,
    total_latency_ms: index === 1 || index === 2 ? null : 2000 + index * 250,
    server_latency_ms: null, input_tokens: 32, output_tokens: 128, tps: 62 + index,
    error_message: index === 1 ? "ServiceUnavailable: request failed" : index === 2 ? "Vendor overloaded" : null,
    iteration: 1, category: "chat-short",
  }));
  const trend = Array.from({ length: 10 }, (_, sample) => latest.map((result) => ({
    ...result,
    timestamp: timestamp(2 + sample * 5),
    ttft_ms: result.ttft_ms == null ? null : result.ttft_ms + sample * 20,
  }))).flat();
  return {
    latest, trend,
    status: {
      is_running: true, current_cycle_running: false, interval_seconds: 300,
      last_run_time: timestamp(2), next_run_time: timestamp(-3),
      last_completed_time: timestamp(2), expected_model_count: 6,
    },
    anomalies: {
      hours: 12, total_probes: 100, total_failures: 3,
      models: [{ model_name: modelCatalog[1].name, failures: 3, total: 20, last_error: "ServiceUnavailable" }],
    },
  };
}

export const categories = [
  { id: "chat-short", label_ko: "짧은 대화", label_en: "Short chat" },
  { id: "reasoning", label_ko: "추론", label_en: "Reasoning" },
  { id: "code-gen", label_ko: "코드 생성", label_en: "Code generation" },
  { id: "summarize", label_ko: "요약", label_en: "Summarize" },
  { id: "structured", label_ko: "JSON 추출", label_en: "Structured" },
  { id: "translate", label_ko: "번역", label_en: "Translate" },
];

/** All API traffic stays in fixtures, including unexpected mutations. */
export async function mockApi(page: Page) {
  const data = monitoringData();
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const values: Record<string, unknown> = {
      "/api/models": modelCatalog,
      "/api/prompts": [],
      "/api/auto-probe/status": data.status,
      "/api/auto-probe/latest": data.latest,
      "/api/auto-probe/trend": data.trend,
      "/api/auto-probe/anomalies": data.anomalies,
      "/api/auto-probe/categories": categories,
      "/api/insights/latest": null,
    };
    const body = values[url.pathname];
    await route.fulfill({
      status: body === undefined ? 404 : 200,
      contentType: "application/json",
      body: JSON.stringify(body === undefined ? { detail: "Unmocked API request" } : body),
    });
  });
  return data;
}
