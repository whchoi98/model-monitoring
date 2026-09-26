"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  fetchAutoStatus, fetchAutoLatest, fetchAutoTrend, triggerAutoProbe,
  fetchWorkloadCategories, fetchModels, fetchAutoAnomalies,
} from "@/lib/api";
import { ApiError } from "@/lib/http";
import { useT, useLang } from "@/lib/i18n-context";
import { useAuth } from "@/lib/auth-context";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { isExcludedModel, sortResults } from "@/lib/sortModels";
import { defaultTrendSelection, parseTrendQuery } from "@/lib/trendSelection";
import { buildMonitoringRows, cadenceResolver, filterMonitoringRows, getFreshness, type HealthFilter, type ModelSort } from "@/lib/monitoring";
import { formatAge, formatDateTime, parseTimestamp } from "@/lib/format";
import ModelStatusGrid from "./ModelStatusGrid";
import MonitoringOverview from "./MonitoringOverview";
import TrendChart from "./TrendChart";
import InsightsPanel from "./InsightsPanel";
import RefreshControls from "./RefreshControls";
import { DataEmpty, DataError, DataLoading } from "./DataState";

const TREND_RANGE_HOURS = [1 / 12, 1 / 6, 0.25, 0.5, 1, 3, 6, 12, 24, 72, 120, 168];
const HEALTH_FILTERS: HealthFilter[] = ["all", "healthy", "attention", "error", "stale"];
const MODEL_SORTS: ModelSort[] = ["family", "attention", "ttft"];
// /status channel_intervals keys (model_id prefix) → display name. Product names are not translated.
const CHANNEL_LABELS: Record<string, string> = { anthropic: "Claude Platform on AWS" };

/** Named channels whose cadence differs from the base one, for the cadence text (v2.29.0). */
function channelCadenceNotes(overrides: Record<string, number> | undefined, baseSeconds: number): [string, number][] {
  return Object.entries(overrides ?? {})
    .filter(([key, seconds]) => CHANNEL_LABELS[key] && Number.isFinite(seconds) && seconds > 0 && seconds !== baseSeconds)
    .map(([key, seconds]) => [CHANNEL_LABELS[key], seconds / 60]);
}

/** Next's history adapter copies its internal state and notifies useSearchParams. */
function updateQuery(updates: Record<string, string | null>) {
  const url = new URL(window.location.href);
  for (const [key, value] of Object.entries(updates)) {
    if (value === null || value === "") url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  }
  window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
}

export default function AutoDashboard() {
  const t = useT();
  const m = t.monitoring;
  const { lang } = useLang();
  const { user, openLogin } = useAuth();
  const params = useSearchParams();
  const query = useMemo(() => parseTrendQuery(params.toString()), [params]);
  const modelsParam = params.get("models") ?? "";
  const selectedModels = useMemo(() => new Set(Array.from(
    parseTrendQuery(`?models=${encodeURIComponent(modelsParam)}`).models ?? [],
  ).filter((name) => !isExcludedModel(name))), [modelsParam]);
  const category = query.category;
  const hours = query.hours !== undefined && TREND_RANGE_HOURS.includes(query.hours) ? query.hours : 1;
  const search = params.get("q") ?? "";
  const healthFilter = HEALTH_FILTERS.includes(params.get("health") as HealthFilter) ? params.get("health") as HealthFilter : "all";
  const sort = MODEL_SORTS.includes(params.get("sort") as ModelSort) ? params.get("sort") as ModelSort : "family";

  const status = useAsyncResource("auto-status", fetchAutoStatus);
  const latest = useAsyncResource(`auto-latest:${category ?? ""}`, (signal) => fetchAutoLatest(category, signal));
  const trend = useAsyncResource(`auto-trend:${hours}:${category ?? ""}`, (signal) => fetchAutoTrend(hours, category, signal));
  const anomalies = useAsyncResource(`auto-anomalies:${category ?? ""}`, (signal) => fetchAutoAnomalies(12, category, signal));
  const catalog = useAsyncResource("model-catalog", fetchModels);
  const workloads = useAsyncResource("workload-categories", fetchWorkloadCategories);
  const [now, setNow] = useState(Date.now());
  const [triggering, setTriggering] = useState(false);
  const [triggerMessage, setTriggerMessage] = useState<{ kind: "success" | "error"; text: string } | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const refresh = useCallback(async () => {
    await Promise.allSettled([status.refresh(), latest.refresh(), trend.refresh(), anomalies.refresh(), catalog.refresh(), workloads.refresh()]);
  }, [status.refresh, latest.refresh, trend.refresh, anomalies.refresh, catalog.refresh, workloads.refresh]);
  const autoRefresh = useAutoRefresh(refresh);
  const refreshing = status.refreshing || latest.refreshing || trend.refreshing || anomalies.refreshing;
  const interval = status.data?.interval_seconds ?? 300;
  const cadence = category ? status.data?.category_interval_seconds ?? interval * (workloads.data?.length || 6) : interval;
  // Per-channel cadence (v2.29.0): /status channel_intervals can give Claude Platform on AWS its own cadence
  // (600 s when the ANTHROPIC_CP_PROBE_INTERVAL_S knob is raised); since v2.29.1 it defaults to the base one.
  // Serialized so a status refresh with the same values keeps the resolver (and the memoized charts) stable.
  // /status가 아직 없거나 실패하면 모든 채널에 기본 주기를 쓴다(v2.29.1 — CP도 매 사이클 수집). /status가 오면 그 값이 우선한다.
  const channelCadenceJson = JSON.stringify((category ? status.data?.channel_category_intervals : status.data?.channel_intervals) ?? {});
  const channelCadence = useMemo(() => JSON.parse(channelCadenceJson) as Record<string, number>, [channelCadenceJson]);
  const cadenceFor = useMemo(() => cadenceResolver(cadence, channelCadence), [cadence, channelCadence]);
  const cycleNotes = channelCadenceNotes(status.data?.channel_intervals, interval);
  const categoryNotes = channelCadenceNotes(status.data?.channel_category_intervals, cadence);
  const nowMinute = Math.floor(now / 60_000) * 60_000;
  const rows = useMemo(
    () => buildMonitoringRows(catalog.data, latest.data ?? [], cadenceFor, nowMinute),
    [catalog.data, latest.data, cadenceFor, nowMinute],
  );
  const visibleRows = useMemo(() => filterMonitoringRows(rows, search, healthFilter, sort), [rows, search, healthFilter, sort]);
  const chartData = useMemo(() => (trend.data ?? []).filter((point) => !isExcludedModel(point.model_name)), [trend.data]);
  const availableModels = useMemo(() => {
    const names = new Set([...rows.map((row) => row.model.name), ...chartData.map((point) => point.model_name)]);
    return sortResults(Array.from(names, (model_name) => ({ model_name }))).map((row) => row.model_name);
  }, [rows, chartData]);

  const selectModels = useCallback((models: Set<string>) => {
    updateQuery({ models: models.size ? Array.from(models).sort().join(",") : "all" });
  }, []);
  const toggleModel = useCallback((name: string) => {
    const selected = parseTrendQuery(window.location.search).models ?? new Set<string>();
    if (selected.has(name)) selected.delete(name);
    else selected.add(name);
    selectModels(selected);
  }, [selectModels]);
  const resetCardFilters = () => updateQuery({ q: null, health: null, sort: null });

  const lastRun = status.data?.last_run_time;
  const nextRun = parseTimestamp(status.data?.next_run_time);
  const collectionStale = getFreshness(lastRun, interval, now) !== "fresh";
  const reportedState = status.error ? "unknown" : status.data?.cycle_state
    ?? (status.data?.current_cycle_running ? "running" : !lastRun ? "unknown" : collectionStale ? "overdue" : "waiting");
  const runningAge = now - (parseTimestamp(lastRun) ?? status.updatedAt ?? now);
  const expiredRunning = reportedState === "running" && runningAge >= (status.data?.running_timeout_seconds ?? 900) * 1000;
  const cycleState = expiredRunning ? "overdue" : reportedState === "completed" ? (collectionStale ? "overdue" : "waiting") : reportedState;
  const cycleLabel = cycleState === "running" ? t.cycleRunning : cycleState === "waiting" ? t.waiting
    : cycleState === "overdue" ? m.overdue : cycleState === "failed" ? m.failed : m.unverified;
  const nextSeconds = nextRun === null ? null : Math.ceil((nextRun - now) / 1000);
  const nextLabel = nextSeconds === null ? "—" : nextSeconds <= 0 ? (cycleState === "running" ? t.cycleRunning : cycleState === "waiting" ? t.waiting : m.overdue)
    : `${Math.floor(nextSeconds / 60)}:${String(nextSeconds % 60).padStart(2, "0")}`;

  const handleTrigger = async () => {
    if (!user) { openLogin(); return; }
    setTriggering(true);
    setTriggerMessage(null);
    try {
      const response = await triggerAutoProbe();
      setTriggerMessage({ kind: response.triggered ? "success" : "error", text: response.triggered ? m.triggerAccepted : m.triggerBusy });
      await status.refresh();
    } catch (error) {
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) openLogin();
      setTriggerMessage({ kind: "error", text: error instanceof ApiError && error.status === 409 ? m.triggerBusy : m.triggerFailed });
    } finally { setTriggering(false); }
  };

  const filterLabels: Record<HealthFilter, string> = { all: m.allStatuses, healthy: m.healthy, attention: m.attention, error: m.failuresOnly, stale: m.staleOnly };
  const selectedMissing = Array.from(selectedModels).some((name) => !availableModels.includes(name));
  const selectedWorkload = workloads.data?.find((workload) => workload.id === category);
  const scopeLabel = category ? (lang === "en" ? selectedWorkload?.label_en : selectedWorkload?.label_ko) ?? category : t.workloadAll;
  const catalogKnown = catalog.data !== null && !catalog.error;
  const unlistedCount = !catalogKnown ? Math.max(0, (status.data?.expected_model_count ?? rows.length) - rows.length) : 0;

  return (
    <div className="mx-auto max-w-7xl space-y-5 p-4 sm:space-y-6 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-gray-100">{m.title}</h1>
          <p className="mt-1 text-sm text-gray-500">{m.description}</p>
        </div>
        <nav aria-label={m.overview} className="flex flex-wrap gap-2">
          <a className="ui-button" href="#model-status">{t.modelStatus}</a>
          <a className="ui-button" href="#performance-trends">{m.viewTrends}</a>
          <Link className="ui-button" href="/reliability">{m.viewReliability}</Link>
        </nav>
      </div>

      <DataError error={catalog.error} resource={m.catalog} onRetry={catalog.refresh} hasData={!!catalog.data} />
      <DataError error={latest.error} resource={m.latestResults} onRetry={latest.refresh} hasData={latest.data !== null} />
      {latest.loading && <DataLoading />}
      {latest.data !== null && (
        <div className="space-y-2">
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-gray-500">
            <span>{t.workloadLabel}: <span className="text-gray-300">{scopeLabel}</span></span>
            <span>{t.common.updatedAt}: {formatAge(latest.updatedAt, lang, now)}</span>
          </p>
          <MonitoringOverview rows={rows} catalogKnown={catalogKnown} expectedCount={status.data?.expected_model_count} filter={healthFilter}
            onFilterChange={(value) => updateQuery({ health: value === "all" ? null : value, q: null })}
            selectedModels={selectedModels} onToggleModel={toggleModel} />
        </div>
      )}

      <section aria-label={t.autoProbeStatus} className="space-y-3 rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs">
            <span className="font-semibold text-gray-300">{m.collection}</span>
            <span className={`whitespace-nowrap rounded-full border px-2.5 py-1 font-medium ${cycleState === "waiting" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-300" : cycleState === "running" ? "border-blue-500/30 bg-blue-500/10 text-blue-300" : "border-amber-500/30 bg-amber-500/10 text-amber-300"}`}>{cycleLabel}</span>
            <span className="text-gray-500">{m.cadence(interval / 60)}</span>
            {cycleNotes.map(([label, minutes]) => <span key={label} className="text-gray-500">{m.channelCadence(label, minutes)}</span>)}
            <span className="text-gray-500" title={formatDateTime(lastRun, lang)}>{t.lastProbe}: <span className="text-gray-300">{formatAge(lastRun, lang, now)}</span></span>
            <span className="text-gray-500">{t.nextProbe}: <span className="tabular-nums text-gray-300">{nextLabel}</span></span>
          </div>
          <button type="button" onClick={handleTrigger} disabled={triggering || cycleState === "running"} className={user ? "ui-button-primary" : "ui-button"}>
            {triggering ? t.triggering : user ? t.triggerNow : m.loginToTrigger}
          </button>
        </div>
        <div className="border-t border-gray-800 pt-3">
          <RefreshControls refreshing={refreshing} onRefresh={() => { autoRefresh.reset(); void refresh(); }} updatedAt={latest.updatedAt}
            enabled={autoRefresh.enabled} onEnabledChange={autoRefresh.setEnabled} countdown={autoRefresh.countdown} />
        </div>
        {triggerMessage && <p role={triggerMessage.kind === "error" ? "alert" : "status"} className={`text-xs ${triggerMessage.kind === "error" ? "text-amber-300" : "text-blue-300"}`}>{triggerMessage.text}</p>}
      </section>
      <DataError error={status.error} resource={t.autoProbeStatus} onRetry={status.refresh} hasData={!!status.data} />

      <section aria-label={t.workloadLabel} className="rounded-xl border border-gray-800 bg-gray-900/50 p-3">
        <div className="flex flex-wrap items-center gap-2" role="group" aria-label={t.workloadLabel}>
          <span className="mr-1 text-xs font-medium text-gray-400">{t.workloadLabel}</span>
          <button type="button" aria-pressed={category === null} onClick={() => updateQuery({ category: null })} className={category === null ? "ui-button-primary" : "ui-button"}>{t.workloadAll}</button>
          {workloads.data?.map((workload) => (
            <button type="button" key={workload.id} aria-pressed={category === workload.id} onClick={() => updateQuery({ category: workload.id })}
              className={category === workload.id ? "ui-button-primary" : "ui-button"}>{lang === "en" ? workload.label_en : workload.label_ko}</button>
          ))}
        </div>
        {category && (
          <p className="mt-2 text-xs text-gray-500">
            {[m.categoryCadence(cadence / 60), ...categoryNotes.map(([label, minutes]) => m.categoryChannelCadence(label, minutes))].join(" ")}
          </p>
        )}
      </section>
      <DataError error={workloads.error} resource={t.workloadLabel} onRetry={workloads.refresh} hasData={!!workloads.data} />

      <DataError error={anomalies.error} resource={m.recentFailures} onRetry={anomalies.refresh} hasData={!!anomalies.data} />
      {anomalies.data && (
        <section aria-label={m.recentFailures} className={`rounded-xl border p-4 ${anomalies.data.total_failures > 0 ? "border-rose-500/30 bg-rose-500/5" : "border-gray-800 bg-gray-900/50"}`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className={`text-sm font-medium ${anomalies.data.total_failures ? "text-rose-300" : "text-gray-300"}`}>
              {anomalies.data.total_probes === 0 ? m.noProbes : anomalies.data.total_failures ? m.recentFailuresTitle(anomalies.data.total_failures) : m.noFailures}
            </h2>
            <span className="text-xs text-gray-500">{m.probeCount(anomalies.data.total_probes)}</span>
          </div>
          {anomalies.data.models.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {anomalies.data.models.slice(0, 8).map((model) => (
                <button type="button" key={model.model_name} onClick={() => { selectModels(new Set([model.model_name])); document.getElementById("performance-trends")?.scrollIntoView(); }}
                  className="min-h-9 rounded-lg border border-rose-500/25 px-2.5 py-1.5 text-left text-xs text-rose-300 hover:bg-rose-500/10" title={model.last_error ?? undefined}>
                  {model.model_name} <span className="font-mono">×{model.failures}</span>
                </button>
              ))}
              <Link href="/reliability" className="ui-button">{m.viewReliability}</Link>
            </div>
          )}
        </section>
      )}

      {latest.data !== null && (
        <section id="model-status" aria-label={t.modelStatus} className="space-y-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-gray-100">{t.modelStatus}</h2>
              <p className="mt-1 text-xs text-gray-500">{m.selectHint}</p>
            </div>
            <span className="text-xs tabular-nums text-gray-500">{m.visibleCount(visibleRows.length, rows.length + unlistedCount)}</span>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <label className="min-w-0 flex-1 sm:max-w-sm">
              <span className="sr-only">{m.search}</span>
              <input type="search" value={search} onChange={(event) => updateQuery({ q: event.target.value })} placeholder={m.searchPlaceholder} className="ui-input w-full" />
            </label>
            <label>
              <span className="sr-only">{m.sort}</span>
              <select className="ui-input text-xs" value={sort} onChange={(event) => updateQuery({ sort: event.target.value })}>
                <option value="family">{m.sortFamily}</option><option value="attention">{m.sortAttention}</option><option value="ttft">{m.sortTtft}</option>
              </select>
            </label>
            {(search || healthFilter !== "all" || sort !== "family") && <button type="button" className="ui-button" onClick={resetCardFilters}>{t.common.resetFilters}</button>}
          </div>
          <div className="flex flex-wrap gap-2" role="group" aria-label={m.statusFilter}>
            {HEALTH_FILTERS.map((filter) => <button type="button" key={filter} aria-pressed={healthFilter === filter} onClick={() => updateQuery({ health: filter === "all" ? null : filter })} className={healthFilter === filter ? "ui-button-primary" : "ui-button"}>{filterLabels[filter]}</button>)}
          </div>
          {selectedModels.size > 0 && (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-blue-500/30 bg-blue-500/10 px-4 py-3">
              <span className="text-xs font-medium text-blue-300">{m.selection(selectedModels.size)}</span>
              <a href="#performance-trends" className="ui-button-primary">{m.compareSelection}</a>
              <button type="button" className="ui-button" onClick={() => selectModels(new Set())}>{m.clearSelection}</button>
            </div>
          )}
          {visibleRows.length > 0 ? <ModelStatusGrid rows={visibleRows} grouped={sort === "family"} selectedModels={selectedModels} onToggleModel={toggleModel} now={nowMinute} /> : (
            <DataEmpty title={unlistedCount ? m.catalogRequired : rows.length ? m.noMatchingModels : t.noDataYet}
              description={unlistedCount ? m.unlistedChannels(unlistedCount) : rows.length ? t.common.noDataHint : t.noDataDesc}>
              {unlistedCount ? <button type="button" className="ui-button" onClick={catalog.refresh}>{t.common.retry}</button>
                : rows.length > 0 && <button type="button" className="ui-button" onClick={resetCardFilters}>{t.common.resetFilters}</button>}
            </DataEmpty>
          )}
        </section>
      )}

      <section id="performance-trends" aria-label={m.trends} className="space-y-4">
        <div>
          <h2 className="text-lg font-semibold text-gray-100">{m.trends}</h2>
          <p className="mt-1 text-xs leading-relaxed text-gray-500">{m.trendHint}</p>
        </div>
        <div role="group" aria-label={t.trendRange} className="flex flex-wrap items-center gap-2">
          <span className="mr-1 shrink-0 text-xs font-medium text-gray-400">{t.trendRange}</span>
          {TREND_RANGE_HOURS.map((range) => <button type="button" key={range} aria-pressed={hours === range} onClick={() => updateQuery({ hours: String(range) })} className={hours === range ? "ui-button-primary" : "ui-button"}>{t.trendRangeLabel(range)}</button>)}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className={selectedModels.size === 0 ? "ui-button-primary" : "ui-button"} onClick={() => selectModels(new Set())} aria-pressed={selectedModels.size === 0}>{t.allModels}</button>
          <button type="button" className="ui-button" onClick={() => selectModels(defaultTrendSelection(availableModels))} title={t.repModelsHint}>{t.repModels}</button>
          {selectedModels.size > 0 && <span className="text-xs text-gray-400">{m.selection(selectedModels.size)}</span>}
        </div>
        <details className="rounded-xl border border-gray-800 bg-gray-900/50 p-3" open={selectedModels.size > 0 ? true : undefined}>
          <summary className="cursor-pointer text-xs font-medium text-gray-300">{m.selectHint}</summary>
          <div className="mt-3 flex max-h-52 flex-wrap gap-2 overflow-auto p-1">
            {Array.from(new Set([...availableModels, ...Array.from(selectedModels)])).map((name) => (
              <button type="button" key={name} onClick={() => toggleModel(name)} aria-pressed={selectedModels.has(name)} className={selectedModels.has(name) ? "ui-button-primary text-left" : "ui-button text-left"}>
                {selectedModels.has(name) ? "✓ " : ""}{name}
              </button>
            ))}
          </div>
        </details>
        {selectedMissing && <p className="text-xs text-amber-300">{m.selectionMissing}</p>}
        <DataError error={trend.error} resource={m.trends} onRetry={trend.refresh} hasData={trend.data !== null} />
        {trend.loading ? <DataLoading /> : trend.data !== null && chartData.length === 0 ? <DataEmpty title={m.noTrend} description={m.noTrendHint} /> : chartData.length > 0 && (
          <div className="space-y-4" aria-busy={trend.refreshing}>
            <TrendChart data={chartData} metric="ttft_ms" title={t.ttftTrend} selectedModels={selectedModels} onToggleModel={toggleModel} cadenceSeconds={hours > 24 ? 3600 : cadenceFor} />
            <TrendChart data={chartData} metric="total_latency_ms" title={t.latencyTrend} selectedModels={selectedModels} onToggleModel={toggleModel} cadenceSeconds={hours > 24 ? 3600 : cadenceFor} />
            <TrendChart data={chartData} metric="tps" title={t.tpsTrend} selectedModels={selectedModels} onToggleModel={toggleModel} cadenceSeconds={hours > 24 ? 3600 : cadenceFor} />
          </div>
        )}
      </section>

      <InsightsPanel />
      <details className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <summary className="cursor-pointer text-sm font-semibold text-gray-200">{m.metricGuide}</summary>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          {Object.entries(t.metrics).map(([key, metric]) => <div key={key} className="text-xs"><span className="font-medium text-gray-300">{metric.name} ({metric.unit})</span><p className="mt-1 leading-relaxed text-gray-500">{metric.desc}</p></div>)}
        </div>
      </details>
      <details className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <summary className="cursor-pointer text-sm font-semibold text-gray-200">{m.channelsGuide}</summary>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          {Object.values(t.channels).map((channel) => <div key={channel.name} className="text-xs"><span className="font-semibold text-gray-300">{channel.name}</span><p className="mt-1 leading-relaxed text-gray-500">{channel.desc}</p><code className="mt-2 block break-all text-blue-300">{channel.endpoint}</code></div>)}
        </div>
      </details>
    </div>
  );
}
