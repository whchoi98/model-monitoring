"use client";

import PageHeading from "./PageHeading";
import { useT as usePageCopy } from "@/lib/i18n-context";

// Model Explorer (v2.9.0) — 모니터링 중인 전체 모델 카드 그리드 + 상세 모달.
// 참조 UX: aws-samples Bedrock Central의 Explore Models (검색/필터 + 카드 + 상세).
// 카드 목록은 /api/models(공개)에서 — 모델 추가 시 자동 반영, 하드코딩 없음.
// 단가는 /api/pricing `models`를 페이지에서 한 번 받아 카드와 상세에 내려준다 (v2.30.0).
// 코드 예제와 매일 검증 결과는 /api/explorer/latest에서 온다 (v2.40.0, ADR-035): 예제를 만드는 함수가 백엔드
// 하나라 화면의 코드가 곧 검증 런이 실행한 코드다. 이 API가 실패해도 카드는 /api/models만으로 그리고, 상세 모달의
// 코드 영역만 재시도를 보여 준다.

import { useCallback, useId, useMemo, useRef, useState } from "react";
import { ExplorerExample, ExplorerLatest, ModelInfo, PricingModelPrice, PricingResponse } from "@/lib/types";
import { fetchExplorerLatest, fetchModels, fetchPricing, triggerExplorerRun } from "@/lib/api";
import { ApiError } from "@/lib/http";
import { useAuth } from "@/lib/auth-context";
import { useLang, useT } from "@/lib/i18n-context";
import { formatDateTime, parseTimestamp } from "@/lib/format";
import { formatDuration } from "@/lib/claudeFeatures";
import { formatUnitPrice, formatPricePair } from "@/lib/pricingTable";
import { sortResults, isExcludedModel } from "@/lib/sortModels";
import {
  badgeLabel, changedModelIds, changeKindLabel, formatLatency, hasFailure, reasonText, splitError, statusLabel,
  summarizeChanges, summarizeModel, type ModelGrade,
} from "@/lib/explorerVerify";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { useRunPolling } from "@/hooks/useRunPolling";
import { DataEmpty, DataError, DataLoading } from "@/components/DataState";
import Dialog from "@/components/Dialog";
import ModelName from "@/components/ModelName";
import RefreshControls from "@/components/RefreshControls";
import {
  ChannelType,
  channelOf,
  modelLinks,
  nativeId,
} from "@/lib/modelExplorer";

type Lang = "ko" | "en";

const CHANNEL_FILTERS: { id: ChannelType | "all"; ko: string; en: string }[] = [
  { id: "all", ko: "전체", en: "All" },
  { id: "anthropic-cp", ko: "Anthropic CP", en: "Anthropic CP" },
  { id: "bedrock", ko: "Bedrock", en: "Bedrock" },
  { id: "openai-mantle", ko: "OpenAI Mantle", en: "OpenAI Mantle" },
  { id: "openai-1p", ko: "OpenAI 1P", en: "OpenAI 1P" },
];

const CHANNEL_BADGE: Record<ChannelType, string> = {
  "anthropic-cp": "bg-purple-500/10 border-purple-500/30 text-purple-300",
  bedrock: "bg-orange-500/10 border-orange-500/30 text-orange-300",
  "openai-mantle": "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  "openai-1p": "bg-teal-500/10 border-teal-500/30 text-teal-300",
};

const GRADE_BADGE: Record<ModelGrade, string> = {
  passed: "bg-emerald-500/10 border-emerald-500/30 text-emerald-300",
  failed: "bg-rose-500/10 border-rose-500/30 text-rose-300",
  skipped: "bg-gray-800 border-gray-700 text-gray-400",
  none: "bg-gray-800 border-gray-700 text-gray-400",
};

const STALE_RUN_MS = 26 * 3_600_000;

function CopyButton({ text, label }: { text: string; label: string }) {
  const { lang } = useLang();
  const [result, setResult] = useState<{
    text: string; status: "copying" | "copied" | "error";
  } | null>(null);
  // Feedback belongs to the copied text, including when a different code tab opens.
  const status = result?.text === text ? result.status : "idle";
  const copy = async () => {
    setResult({ text, status: "copying" });
    try {
      await navigator.clipboard.writeText(text);
      setResult({ text, status: "copied" });
    } catch {
      setResult({ text, status: "error" });
    }
  };

  return (
    <div className="flex max-w-full flex-col items-start gap-1">
      <button type="button" onClick={() => void copy()} disabled={status === "copying"}
              aria-label={label} className="ui-button shrink-0">
        {status === "copying" ? (lang === "en" ? "Copying…" : "복사 중…")
          : status === "copied" ? (lang === "en" ? "✓ Copied" : "✓ 복사됨")
            : status === "error" ? (lang === "en" ? "Retry copy" : "다시 복사")
              : (lang === "en" ? "Copy" : "복사")}
      </button>
      <span role="status" aria-atomic="true"
            className={`text-[11px] leading-relaxed ${status === "error" ? "text-rose-400" : "text-gray-500"}`}>
        {status === "copied" ? (lang === "en" ? "Copied to clipboard." : "클립보드에 복사했습니다.")
          : status === "error" ? (lang === "en" ? "Copy failed. Select the text to copy manually." : "복사하지 못했습니다. 텍스트를 선택해 직접 복사하세요.")
            : ""}
      </span>
    </div>
  );
}

/** The verification box under an example's description (v2.40.0). */
function VerifyBox({ example, lang }: { example: ExplorerExample; lang: Lang }) {
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const result = example.result;
  if (!result) {
    return (
      <p data-verify="none" className="mb-2 rounded-md border border-gray-800 bg-gray-950/50 p-2.5 text-xs text-gray-400">
        {L("Not verified yet.", "아직 검증하지 않았습니다.")}
      </p>
    );
  }
  const when = `${formatDateTime(result.verified_at, lang)} (${L("run", "런")} #${result.run_id})`;
  const stale = result.stale_code && (
    <p className="mt-1.5 text-amber-300">
      {L(`This example changed after the last verification (run #${result.run_id}). The next run verifies it again.`,
         `이 예제는 마지막 검증(런 #${result.run_id}) 뒤에 바뀌었습니다. 다음 런에서 다시 검증합니다.`)}
    </p>
  );
  if (result.status === "passed") {
    return (
      <div data-verify="passed" className="mb-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-2.5 text-xs text-emerald-300">
        <p>{L("Verified", "검증 통과")}, {formatLatency(result.latency_ms, lang)}, {when}</p>
        {result.output_excerpt && (
          <pre className="mt-1.5 whitespace-pre-wrap break-all font-mono text-[11px] text-gray-300">{result.output_excerpt}</pre>
        )}
        {stale}
      </div>
    );
  }
  const message = result.error_message ?? "";
  if (result.status === "skipped") {
    return (
      <div data-verify="skipped" className="mb-2 rounded-md border border-gray-700 bg-gray-950/50 p-2.5 text-xs text-gray-400">
        <p>{L("Skipped", "건너뜀")}: {reasonText(message, lang)}, {when}</p>
        {stale}
      </div>
    );
  }
  const { head, tail } = splitError(message);
  return (
    <div data-verify="failed" role="status" className="mb-2 rounded-md border border-rose-500/30 bg-rose-500/10 p-2.5 text-xs text-rose-300">
      <p>
        {result.attempts > 1 ? L("Still failing after a retry", "다시 시도 뒤에도 실패") : L("Verification failed", "검증 실패")}, {when}
      </p>
      <p className="mt-1 break-all font-mono text-[11px] text-rose-200">{reasonText(head, lang)}</p>
      {tail && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-gray-400">{L("Error output", "오류 출력")}</summary>
          <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-all font-mono text-[11px] text-gray-300">{tail}</pre>
        </details>
      )}
      {stale}
    </div>
  );
}

function DetailModal({ model, price, explorer, explorerError, explorerLoading, onRetryExplorer, initialApi, onClose }: {
  model: ModelInfo;
  price: PricingModelPrice | null;
  explorer: ExplorerLatest | null;
  explorerError: Error | null;
  explorerLoading: boolean;
  onRetryExplorer: () => void;
  initialApi: string | null;
  onClose: () => void;
}) {
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const ch = channelOf(model.id);
  const examples = explorer?.models[model.id]?.examples ?? null;
  const links = modelLinks(model.id, model.name, lang === "en" ? "en" : "ko");
  const [tab, setTab] = useState(() => {
    const at = examples?.findIndex((example) => example.api_id === initialApi) ?? -1;
    return at < 0 ? 0 : at;
  });
  const tabsId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = examples && examples.length > 0 ? examples[Math.min(tab, examples.length - 1)] : null;
  const code = current ? current.code[lang] : "";

  return (
    <Dialog title={<ModelName name={model.name} />} onClose={onClose}>
        {/* 헤더 */}
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`px-2 py-0.5 text-[11px] font-medium rounded-full border ${CHANNEL_BADGE[ch.type]}`}>
              {ch.label}
            </span>
          </div>
          <code className="mt-2 block text-xs text-blue-300 break-all">{model.id}</code>
        </div>

        {/* 모델 정보 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
          <div className="min-w-0 bg-gray-950/50 border border-gray-800 rounded-md p-3 space-y-1.5">
            <div className="text-gray-500">{L("Invoke model ID", "호출 모델 ID")}</div>
            <div className="flex flex-col items-start gap-2">
              <code className="text-gray-200 break-all">{nativeId(model.id)}</code>
              <CopyButton text={nativeId(model.id)} label={L("Copy model ID", "모델 ID 복사")} />
            </div>
            <div className="text-gray-500 pt-1">{L("Endpoint", "엔드포인트")}</div>
            <code className="text-gray-300 break-all">{ch.endpoint}</code>
            <div className="text-gray-500 pt-1">{L("Region", "리전")}</div>
            <div className="text-gray-300">{ch.region}</div>
          </div>
          <div className="min-w-0 bg-gray-950/50 border border-gray-800 rounded-md p-3 space-y-1.5">
            <div className="text-gray-500">{L("Pricing (per 1M tokens)", "토큰 단가 (1M 기준)")}</div>
            {price ? (
              <div className="text-gray-200 tabular-nums">
                {L("Input", "입력")} <span className="font-semibold">{formatUnitPrice(price.input)}</span>
                {" / "}{L("Output", "출력")} <span className="font-semibold">{formatUnitPrice(price.output)}</span>
              </div>
            ) : (
              <div className="text-gray-500">{L("Pricing unavailable", "단가 정보 없음")}</div>
            )}
            <div className="text-gray-500 pt-2">{L("Links", "연결 링크")}</div>
            <ul className="space-y-1">
              {links.map((l) => (
                <li key={l.url}>
                  <a
                    href={l.url}
                    target={l.url.startsWith("/") ? undefined : "_blank"}
                    rel="noopener noreferrer"
                    className="text-blue-400 hover:underline focus-visible:underline"
                  >
                    {l.label} {l.url.startsWith("/") ? "" : "↗"}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>

        {/* 코드 예제 — 백엔드 단일 출처 (v2.40.0) */}
        <div>
          <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
            <h3 className="text-sm font-semibold text-gray-200">{L("Code Examples", "코드 예제")}</h3>
            {current && <CopyButton text={code} label={L("Copy code example", "코드 예제 복사")} />}
          </div>
          {!explorer && explorerError && (
            <DataError error={explorerError} resource={L("code examples", "코드 예제")} onRetry={onRetryExplorer} />
          )}
          {!explorer && !explorerError && explorerLoading && <DataLoading />}
          {explorer && !current && (
            <p className="text-xs text-gray-400">{L("Could not load the code examples for this model.", "이 모델의 코드 예제를 불러오지 못했습니다.")}</p>
          )}
          {examples && current && (
            <>
              {/* API 종류 탭 — Converse / InvokeModel / Messages / Responses */}
              <div role="tablist" aria-label={L("Code example API", "코드 예제 API")} className="flex flex-wrap gap-1 mb-2">
                {examples.map((ex, i) => (
                  <button
                    key={ex.api_id}
                    ref={(element) => { tabRefs.current[i] = element; }}
                    type="button"
                    role="tab"
                    id={`${tabsId}-${i}`}
                    aria-controls={`${tabsId}-panel`}
                    aria-selected={current === ex}
                    tabIndex={current === ex ? 0 : -1}
                    onClick={() => setTab(i)}
                    onKeyDown={(event) => {
                      const next = event.key === "ArrowRight" ? (i + 1) % examples.length
                        : event.key === "ArrowLeft" ? (i - 1 + examples.length) % examples.length
                          : event.key === "Home" ? 0 : event.key === "End" ? examples.length - 1 : null;
                      if (next === null) return;
                      event.preventDefault();
                      setTab(next);
                      tabRefs.current[next]?.focus();
                    }}
                    className={current === ex ? "ui-button-primary" : "ui-button"}
                  >
                    {ex.api}
                  </button>
                ))}
              </div>
              <div role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${examples.indexOf(current)}`} className="min-w-0">
                {/* 선택된 API가 의미하는 바 */}
                <p className="text-xs text-gray-400 leading-relaxed mb-2 bg-blue-500/10 border border-blue-500/20 rounded-md p-2.5">
                  <span className="font-semibold text-gray-200">{current.api}</span>
                  {" — "}
                  {current.description[lang]}
                </p>
                <VerifyBox example={current} lang={lang} />
                <div className="text-xs text-gray-500 mb-1">{current.label}</div>
                <pre tabIndex={0} aria-label={L(`${current.api} code example`, `${current.api} 코드 예제`)}
                     className="bg-gray-950 border border-gray-800 rounded-md p-3 overflow-x-auto text-xs text-gray-200 leading-relaxed ui-table-shell">
                  <code>{code}</code>
                </pre>
              </div>
            </>
          )}
        </div>
    </Dialog>
  );
}

export default function ModelExplorer() {
  const pageCopy = usePageCopy().workspace;
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const t = useT();
  const { user, openLogin } = useAuth();
  const resource = useAsyncResource<ModelInfo[]>("model-catalog", fetchModels);
  const pricing = useAsyncResource<PricingResponse>("pricing", fetchPricing);
  const explorerResource = useAsyncResource<ExplorerLatest>("explorer-latest", fetchExplorerLatest);
  const explorer = explorerResource.data;
  const armRunPolling = useRunPolling({
    running: !!explorer?.running,
    runId: explorer?.run?.id ?? null,
    refresh: explorerResource.refresh,
    refreshing: explorerResource.refreshing,
  });
  const prices = pricing.data?.models ?? null;
  const priceOf = (id: string): PricingModelPrice | null =>
    prices && Object.prototype.hasOwnProperty.call(prices, id) ? prices[id] : null;
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState<ChannelType | "all">("all");
  const [failuresOnly, setFailuresOnly] = useState(false);
  const [selected, setSelected] = useState<{ model: ModelInfo; api: string | null } | null>(null);
  const [triggerMsg, setTriggerMsg] = useState<string | null>(null);
  const [triggerError, setTriggerError] = useState(false);
  const [triggering, setTriggering] = useState(false);

  const models = useMemo(() => sortResults(
    (resource.data ?? []).filter((model) => !isExcludedModel(model.name))
      .map((model) => ({ ...model, model_name: model.name })),
  ).map(({ id, name }) => ({ id, name })), [resource.data]);
  const examplesOf = useCallback((id: string) => explorer?.models[id]?.examples ?? [], [explorer]);
  const changed = useMemo(() => changedModelIds(explorer?.changes ?? []), [explorer]);
  const resetFilters = () => { setSearch(""); setChannel("all"); setFailuresOnly(false); };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return models.filter((m) => {
      if (channel !== "all" && channelOf(m.id).type !== channel) return false;
      if (q && !m.name.toLowerCase().includes(q) && !m.id.toLowerCase().includes(q)) return false;
      if (failuresOnly && !hasFailure(examplesOf(m.id))) return false;
      return true;
    });
  }, [models, search, channel, failuresOnly, examplesOf]);

  const run = explorer?.run ?? null;
  const duration = formatDuration(run?.started_at ?? null, run?.finished_at ?? null, lang);
  const changes = explorer?.changes ?? [];
  const changeSummary = summarizeChanges(changes);
  const byId = useMemo(() => new Map(models.map((m) => [m.id, m])), [models]);

  const handleTrigger = async () => {
    if (!user) { openLogin(); return; }
    setTriggering(true);
    setTriggerError(false);
    try {
      const response = await triggerExplorerRun();
      setTriggerMsg(response.triggered
        ? L("Verification started. Results refresh when it completes (about 2 minutes).", "검증을 시작했습니다. 완료 후 결과가 갱신됩니다(약 2분).")
        : t.monitoring.triggerBusy);
      if (response.triggered) armRunPolling(explorer?.run?.id ?? null);
      await explorerResource.refresh();
    } catch (error) {
      setTriggerError(true);
      setTriggerMsg(L("Could not start verification. Try again shortly.", "검증을 시작하지 못했습니다. 잠시 후 다시 시도하세요."));
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) openLogin();
    } finally { setTriggering(false); }
  };

  return (
    <div className="page-stack">
      <PageHeading eyebrow={pageCopy.exploreWorkspace} title={<>
            {L("Model Explorer", "모델 탐색")}
          </>} description={<>

          <p className="text-sm text-gray-500 mt-1">
            {L("Select a model for invoke IDs, code examples, and links. Every code example runs once a day.",
               "모델을 선택하면 호출 ID, 코드 예제, 연결 링크를 볼 수 있습니다. 코드 예제는 매일 한 번 실제로 실행해 검증합니다.")}
          </p>
          {run && (
            <p data-explorer-run className="text-xs text-gray-500 mt-1 tabular-nums">
              {L("Last verification run", "최근 검증 런")} #{run.id}, {formatDateTime(run.finished_at, lang)}
              {duration && <>, {L("took", "소요")} {duration}</>}
              {run.totals && <>, {L("passed", "통과")} {run.totals.passed}, {L("failed", "실패")} {run.totals.failed}, {L("skipped", "건너뜀")} {run.totals.skipped}</>}
              {explorer?.running && <span className="ml-2 text-blue-400">● {L("run in progress…", "런 실행 중…")}</span>}
            </p>
          )}
          {!run && explorer?.running && (
            <p className="text-xs text-blue-400 mt-1">● {L("run in progress…", "런 실행 중…")}</p>
          )}
        </>}
        actions={<button type="button" onClick={handleTrigger} disabled={triggering || !!explorer?.running} className="ui-button-primary">
          {L("Run verification", "검증 런 실행")}
        </button>}
        >
        <div className="ui-toolbar justify-between"><RefreshControls
          refreshing={resource.refreshing || pricing.refreshing || explorerResource.refreshing}
          onRefresh={() => { void resource.refresh(); void pricing.refresh(); void explorerResource.refresh(); }}
          updatedAt={resource.updatedAt}
        /></div>
      </PageHeading>

      {triggerMsg && (
        <div role={triggerError ? "alert" : "status"}
             className={`rounded-xl border px-4 py-3 text-xs ${triggerError ? "border-amber-500/30 bg-amber-500/10 text-amber-300" : "border-blue-500/30 bg-blue-500/10 text-blue-300"}`}>
          {triggerMsg}
        </div>
      )}
      {run?.finished_at && Date.now() - (parseTimestamp(run.finished_at) ?? 0) > STALE_RUN_MS && (
        <p role="status" className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300">
          {L("The last completed verification is over 26 hours old. These results may be out of date.", "마지막 완료된 검증이 26시간 이상 지났습니다. 현재 상태와 다를 수 있습니다.")}
        </p>
      )}

      {/* 이전 런 대비 변경 (v2.40.0) — Claude API 기능 검증과 같은 모양: 목록(10건 초과 '외 N건') 또는 '변경 없음' 카드 */}
      {run && explorer && explorer.previous_run_id != null && changes.length > 0 && (
        <details data-explorer-changes className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-xs text-gray-300">
          <summary className="text-sm font-semibold text-amber-300 mb-1 cursor-pointer">
            {L(`Changes since run #${explorer.previous_run_id}: ${changes.length}`, `이전 런(#${explorer.previous_run_id}) 대비 변경 ${changes.length}건`)}
          </summary>
          <div className="text-xs text-gray-400 mb-2">
            {L(`New ${changeSummary.catalog}, example changed ${changeSummary.example}, measured ${changeSummary.measured}`,
               `신규 ${changeSummary.catalog}건, 예제 변경 ${changeSummary.example}건, 실측 변경 ${changeSummary.measured}건`)}
          </div>
          <ul className="space-y-1">
            {changes.slice(0, 10).map((c) => {
              const target = byId.get(c.model_id);
              return (
                <li key={`${c.model_id}|${c.api_id}`} className="flex items-center gap-2 flex-wrap">
                  <span className={`px-1.5 py-px text-[11px] rounded ${c.kind === "measured" ? "bg-gray-800 text-gray-400" : "bg-sky-500/10 text-sky-300"}`}>
                    {changeKindLabel(c.kind, lang)}
                  </span>
                  <button type="button" disabled={!target} onClick={() => target && setSelected({ model: target, api: c.api_id })}
                          className={target ? "text-amber-200 hover:underline" : "text-gray-400 cursor-default"}>
                    {c.model_name}, {c.api}
                  </button>
                  <span className="text-gray-500">:</span>
                  <span className={c.before ? "text-gray-300" : "text-gray-500"}>{statusLabel(c.before, lang)}</span>
                  <span className="text-gray-500">→</span>
                  <span className="text-gray-300">{statusLabel(c.after, lang)}</span>
                </li>
              );
            })}
            {changes.length > 10 && <li className="text-gray-500">{L(`+${changes.length - 10} more`, `외 ${changes.length - 10}건`)}</li>}
          </ul>
        </details>
      )}
      {run && explorer && explorer.previous_run_id != null && changes.length === 0 && (
        <div data-explorer-changes className="ui-panel px-3 py-2 text-xs text-gray-500">
          {L(`No changes since run #${explorer.previous_run_id}.`, `이전 런(#${explorer.previous_run_id}) 대비 변경 없음.`)}
        </div>
      )}

      {/* 검색 + 채널 필터 + 검증 실패만 */}
      <div className="flex items-end gap-3 flex-wrap">
        <label className="flex w-full flex-col gap-2 sm:w-64">
          <span className="text-xs font-medium text-gray-400">{L("Search models", "모델 검색")}</span>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={L("Model name or ID", "모델 이름 또는 ID")}
            className="ui-input w-full"
          />
        </label>
        <div role="group" aria-label={L("Channel filter", "채널 필터")} className="flex gap-1 flex-wrap">
          {CHANNEL_FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              onClick={() => setChannel(f.id)}
              aria-pressed={channel === f.id}
              className={channel === f.id ? "ui-button-primary" : "ui-button"}
            >
              {lang === "en" ? f.en : f.ko}
            </button>
          ))}
        </div>
        <button type="button" onClick={() => setFailuresOnly((value) => !value)} aria-pressed={failuresOnly}
                className={failuresOnly ? "ui-button-primary" : "ui-button"}>
          {L("Failures only", "검증 실패만")}
        </button>
        <button type="button" onClick={resetFilters} disabled={search === "" && channel === "all" && !failuresOnly} className="ui-button">
          {t.common.resetFilters}
        </button>
        {resource.data !== null && (
          <span aria-live="polite" aria-atomic="true" className="self-center text-xs text-gray-500">
            {L(`${filtered.length} / ${models.length} models`, `모델 ${filtered.length} / ${models.length}개`)}
          </span>
        )}
      </div>

      <DataError error={resource.error} resource={L("model catalog", "모델 카탈로그")}
                 onRetry={resource.refresh} hasData={models.length > 0} />
      <DataError error={pricing.error} resource={L("unit prices", "비용 단가")}
                 onRetry={pricing.refresh} hasData={prices !== null} />
      <DataError error={explorerResource.error} resource={L("verification results", "검증 결과")}
                 onRetry={explorerResource.refresh} hasData={explorer !== null} />
      {resource.loading && <DataLoading />}
      {!resource.error && resource.data !== null && models.length === 0 && (
        <DataEmpty title={L("No models available.", "등록된 모델이 없습니다.")}
                   description={L("The catalog is empty. Refresh to check for newly registered models.", "카탈로그가 비어 있습니다. 새로고침으로 모델 등록 여부를 확인하세요.")} />
      )}
      {!resource.error && models.length > 0 && filtered.length === 0 && (
        <DataEmpty title={L("No models match these filters.", "검색 조건에 맞는 모델이 없습니다.")}
                   description={L("Change your search or reset the filters to see all models.", "검색어를 바꾸거나 필터를 초기화하면 전체 모델을 볼 수 있습니다.")} />
      )}

      {/* 카드 그리드 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((m) => {
          const ch = channelOf(m.id);
          const price = priceOf(m.id);
          const summary = summarizeModel(examplesOf(m.id));
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => setSelected({ model: m, api: null })}
              aria-label={m.name}
              aria-haspopup="dialog"
              aria-expanded={selected?.model.id === m.id}
              className="ui-panel w-full min-w-0 text-left hover:border-blue-500/50 focus-visible:border-blue-500/50 transition-colors group"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold text-gray-100 group-hover:text-blue-300 group-focus-visible:text-blue-300 transition-colors">
                  <ModelName name={m.name} />
                </h3>
                <span className={`shrink-0 px-2 py-0.5 text-[11px] font-medium rounded-full border ${CHANNEL_BADGE[ch.type]}`}>
                  {ch.badge}
                </span>
              </div>
              <code className="block text-xs text-gray-500 break-all mt-1.5">{m.id}</code>
              <div className="text-xs text-gray-500 mt-2 tabular-nums">
                {price
                  ? `${formatPricePair(price)} ${L("(per 1M tokens, in/out)", "(1M 토큰당 입력/출력)")}`
                  : pricing.loading ? L("Loading prices…", "단가 불러오는 중…")
                    : L("Pricing unavailable", "단가 정보 없음")}
              </div>
              {explorer && (
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <span data-verify-badge={summary.grade}
                        className={`px-2 py-0.5 text-[11px] font-medium rounded-full border ${GRADE_BADGE[summary.grade]}`}>
                    {badgeLabel(summary, lang)}
                  </span>
                  {changed.has(m.id) && (
                    <span data-verify-changed className="px-2 py-0.5 text-[11px] font-medium rounded-full border border-amber-500/40 bg-amber-500/10 text-amber-300">
                      {L("Changed", "변경")}
                    </span>
                  )}
                </div>
              )}
            </button>
          );
        })}
      </div>

      {selected && (
        <DetailModal key={`${selected.model.id}|${selected.api ?? ""}`} model={selected.model} price={priceOf(selected.model.id)}
                     explorer={explorer} explorerError={explorerResource.error} explorerLoading={explorerResource.loading}
                     onRetryExplorer={() => void explorerResource.refresh()} initialApi={selected.api}
                     onClose={() => setSelected(null)} />
      )}
    </div>
  );
}
