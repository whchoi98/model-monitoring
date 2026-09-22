import { describe, expect, test } from "vitest";
import { buildMonitoringRows, filterMonitoringRows, getFreshness, summarizeMonitoring } from "./monitoring";
import type { ProbeResult } from "./types";

const NOW = Date.parse("2026-09-22T12:00:00Z");
const models = [
  { id: "a", name: "Bedrock Claude Fable 5.1 (Global)" },
  { id: "b", name: "Bedrock Claude Fable 5.1 (US)" },
  { id: "c", name: "Anthropic Claude Fable 5.1 (US)" },
  { id: "d", name: "OpenAI GPT 6 Astra (US)" },
  { id: "e", name: "OpenAI GPT 6 Astra (Global)" },
];

function result(id: string, overrides: Partial<ProbeResult> = {}): ProbeResult {
  return {
    model_id: id,
    model_name: models.find((m) => m.id === id)!.name,
    timestamp: "2026-09-22T11:58:00Z",
    status: "success",
    ttft_ms: 500,
    total_latency_ms: 1800,
    server_latency_ms: null,
    input_tokens: 20,
    output_tokens: 80,
    tps: 60,
    iteration: 1,
    ...overrides,
  };
}

describe("monitoring freshness", () => {
  test("a successful request becomes stale after the expected cadence and one cycle of grace", () => {
    expect(getFreshness("2026-09-22T11:50:00Z", 300, NOW)).toBe("fresh");
    expect(getFreshness("2026-09-22T11:49:59Z", 300, NOW)).toBe("stale");
  });

  test("category rotation does not flag a normal 30-minute wait as stale", () => {
    expect(getFreshness("2026-09-22T11:31:00Z", 1800, NOW)).toBe("fresh");
    expect(getFreshness("2026-09-22T11:24:59Z", 1800, NOW)).toBe("stale");
  });

  test("missing, invalid, and future timestamps do not imply healthy monitoring", () => {
    for (const timestamp of [undefined, null, "invalid", "2026-09-23T12:00:00Z"]) {
      expect(getFreshness(timestamp, 300, NOW)).toBe("unknown");
    }
  });

  test("legacy timestamps without an offset are interpreted as UTC", () => {
    expect(getFreshness("2026-09-22T11:58:00", 300, NOW)).toBe("fresh");
    expect(getFreshness("2026-09-22T20:58:00+09:00", 300, NOW)).toBe("fresh");
  });
});

describe("monitoring coverage", () => {
  const results = [
    result("a"),
    result("b", { status: "error", error_message: "Service unavailable" }),
    result("c", { status: "overloaded" }),
    result("d", { timestamp: "2026-09-22T11:30:00Z" }),
  ];

  test("includes unmeasured catalog models and never calls missing or stale success healthy", () => {
    const rows = buildMonitoringRows(models, results, 300, NOW);
    expect(rows.find((r) => r.model.id === "d")?.health).toBe("stale");
    expect(rows.find((r) => r.model.id === "e")?.health).toBe("unknown");
    expect(summarizeMonitoring(rows)).toMatchObject({
      total: 5, observed: 4, healthy: 1, errors: 1, overloaded: 1, stale: 1, unknown: 1, attention: 4,
    });
  });

  test("an empty dataset has no successful samples", () => {
    expect(summarizeMonitoring([])).toMatchObject({ healthy: 0, successRate: null });
  });

  test("latest-run success rate includes stale successes but is explicitly separate from health", () => {
    const summary = summarizeMonitoring(buildMonitoringRows(models, results, 300, NOW));
    expect(summary.successRate).toBe(0.5);
    expect(summary.healthy).toBe(1);
  });

  test("a missing catalog still shows observations without inventing coverage", () => {
    expect(buildMonitoringRows(null, results, 300, NOW)).toHaveLength(4);
  });

  test("deduplicates repeated results by newest sample and excludes retired catalog entries", () => {
    const rows = buildMonitoringRows(models.slice(0, 1), [
      result("a", { timestamp: "2026-09-22T11:40:00Z", status: "error" }),
      result("a"),
      result("b"),
    ], 300, NOW);
    expect(rows).toHaveLength(1);
    expect(rows[0].health).toBe("healthy");
  });

  test("search and attention filters combine without mutating or changing chart selection", () => {
    const rows = buildMonitoringRows(models, results, 300, NOW);
    const filtered = filterMonitoringRows(rows, "  fable  ", "attention", "family");
    expect(filtered.map((r) => r.model.id).sort()).toEqual(["b", "c"]);
    expect(rows).toHaveLength(5);
  });

  test("attention sorting brings failures ahead of successful samples", () => {
    const rows = buildMonitoringRows(models, results, 300, NOW);
    const filtered = filterMonitoringRows(rows, "", "all", "attention");
    expect(filtered[0].health).toBe("error");
    expect(filtered.at(-1)?.health).toBe("healthy");
  });
});
