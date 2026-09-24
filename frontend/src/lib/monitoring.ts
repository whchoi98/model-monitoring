import type { ModelInfo, ProbeResult } from "./types";
import { parseTimestamp } from "./format";
import { isExcludedModel, sortResults } from "./sortModels";

export type Freshness = "fresh" | "stale" | "unknown";
export type ModelHealth = "healthy" | "error" | "overloaded" | "stale" | "unknown";
export type HealthFilter = "all" | "healthy" | "attention" | "error" | "stale";
export type ModelSort = "family" | "attention" | "ttft";

export interface MonitoringRow {
  model: ModelInfo;
  result: ProbeResult | null;
  freshness: Freshness;
  health: ModelHealth;
}

/** Collection cadence (seconds) of one channel, by model_id. */
export type CadenceFor = (modelId: string) => number;

/** The /status channel_intervals key of a model: its model_id prefix before the first ":". */
export function channelKey(modelId: string): string | null {
  const index = modelId.indexOf(":");
  return index > 0 ? modelId.slice(0, index) : null;
}

/**
 * Per-channel cadence from /api/auto-probe/status (v2.29.0). Claude Platform on AWS ("anthropic:<id>") is
 * collected every 10 minutes while every other channel keeps the base 5-minute cadence; channels without an
 * override (or an invalid one) use `baseSeconds`.
 */
export function cadenceResolver(baseSeconds: number, overrides?: Record<string, number> | null): CadenceFor {
  const map = new Map(Object.entries(overrides ?? {}).filter(([, seconds]) => Number.isFinite(seconds) && seconds > 0));
  if (map.size === 0) return () => baseSeconds;
  return (modelId) => {
    const key = channelKey(modelId);
    return (key !== null ? map.get(key) : undefined) ?? baseSeconds;
  };
}

export function getFreshness(
  timestamp: string | null | undefined,
  cadenceSeconds = 300,
  now = Date.now(),
): Freshness {
  const parsed = parseTimestamp(timestamp);
  if (parsed === null || parsed > now + 60_000) return "unknown";
  const cadence = Number.isFinite(cadenceSeconds) && cadenceSeconds > 0 ? cadenceSeconds : 300;
  // One normal collection cycle of grace; category rotation must not double it to an hour.
  const grace = Math.min(cadence, 300);
  return now - parsed > (cadence + grace) * 1000 ? "stale" : "fresh";
}

export function buildMonitoringRows(
  catalog: ModelInfo[] | null,
  results: ProbeResult[],
  cadenceSeconds: number | CadenceFor = 300,
  now = Date.now(),
): MonitoringRow[] {
  const cadenceFor: CadenceFor = typeof cadenceSeconds === "function" ? cadenceSeconds : () => cadenceSeconds;
  const latest = new Map<string, ProbeResult>();
  for (const result of results) {
    if (isExcludedModel(result.model_name)) continue;
    const previous = latest.get(result.model_id);
    if (!previous || (parseTimestamp(result.timestamp) ?? -Infinity) >= (parseTimestamp(previous.timestamp) ?? -Infinity)) {
      latest.set(result.model_id, result);
    }
  }
  const models = catalog ?? Array.from(latest.values(), (result) => ({ id: result.model_id, name: result.model_name }));
  return sortResults(models.filter((model) => !isExcludedModel(model.name)).map((model) => ({
    ...model, model_name: model.name,
  }))).map(({ id, name }) => {
    const result = latest.get(id) ?? null;
    const freshness = getFreshness(result?.timestamp, cadenceFor(id), now);
    const health: ModelHealth = result?.status === "error" ? "error"
      : result?.status === "overloaded" ? "overloaded"
        : freshness === "stale" ? "stale"
          : result?.status === "success" && freshness === "fresh" ? "healthy" : "unknown";
    return { model: { id, name }, result, freshness, health };
  });
}

export function summarizeMonitoring(rows: MonitoringRow[], expectedCount?: number) {
  const total = typeof expectedCount === "number" && Number.isInteger(expectedCount) && expectedCount >= rows.length ? expectedCount : rows.length;
  const unlisted = total - rows.length;
  const observed = rows.filter((row) => row.result !== null).length;
  const successes = rows.filter((row) => row.result?.status === "success").length;
  const healthy = rows.filter((row) => row.health === "healthy").length;
  return {
    total,
    unlisted,
    observed,
    healthy,
    errors: rows.filter((row) => row.health === "error").length,
    overloaded: rows.filter((row) => row.health === "overloaded").length,
    stale: rows.filter((row) => row.health === "stale").length,
    unknown: rows.filter((row) => row.health === "unknown").length + unlisted,
    attention: total - healthy,
    successRate: observed > 0 ? successes / observed : null,
  };
}

const HEALTH_ORDER: Record<ModelHealth, number> = { error: 0, overloaded: 1, stale: 2, unknown: 3, healthy: 4 };

export function filterMonitoringRows(rows: MonitoringRow[], query: string, filter: HealthFilter, sort: ModelSort) {
  const search = query.trim().toLocaleLowerCase();
  const filtered = rows.filter((row) => {
    if (search && !`${row.model.name} ${row.model.id}`.toLocaleLowerCase().includes(search)) return false;
    if (filter === "healthy") return row.health === "healthy";
    if (filter === "attention") return row.health !== "healthy";
    if (filter === "error") return row.health === "error" || row.health === "overloaded";
    if (filter === "stale") return row.freshness !== "fresh";
    return true;
  });
  if (sort === "attention") filtered.sort((a, b) => HEALTH_ORDER[a.health] - HEALTH_ORDER[b.health]);
  if (sort === "ttft") {
    const latency = (row: MonitoringRow) => row.result?.status === "success" ? row.result.ttft_ms ?? -Infinity : -Infinity;
    filtered.sort((a, b) => latency(b) - latency(a));
  }
  return filtered;
}
