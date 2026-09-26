"use client";

// Model Explorer (v2.9.0) — 모니터링 중인 전체 모델 카드 그리드 + 상세 모달.
// 참조 UX: aws-samples Bedrock Central의 Explore Models (검색/필터 + 카드 + 상세).
// 데이터는 /api/models(공개)에서 — 모델 추가 시 자동 반영, 하드코딩 없음.
// 단가는 /api/pricing `models`를 페이지에서 한 번 받아 카드와 상세에 내려준다 (v2.30.0).

import { useId, useMemo, useRef, useState } from "react";
import { ModelInfo, PricingModelPrice, PricingResponse } from "@/lib/types";
import { fetchModels, fetchPricing } from "@/lib/api";
import { useLang, useT } from "@/lib/i18n-context";
import { formatUnitPrice, formatPricePair } from "@/lib/pricingTable";
import { sortResults, isExcludedModel } from "@/lib/sortModels";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { DataEmpty, DataError, DataLoading } from "@/components/DataState";
import Dialog from "@/components/Dialog";
import RefreshControls from "@/components/RefreshControls";
import {
  ChannelType,
  channelOf,
  codeExamples,
  modelLinks,
  nativeId,
} from "@/lib/modelExplorer";

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

function DetailModal({ model, price, onClose }: {
  model: ModelInfo;
  price: PricingModelPrice | null;
  onClose: () => void;
}) {
  const { lang } = useLang();
  const ch = channelOf(model.id);
  const examples = codeExamples(model.id, lang === "en" ? "en" : "ko");
  const links = modelLinks(model.id, model.name, lang === "en" ? "en" : "ko");
  const [tab, setTab] = useState(0);
  const tabsId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);

  return (
    <Dialog title={model.name} onClose={onClose}>
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
            <div className="text-gray-500">{lang === "en" ? "Invoke model ID" : "호출 모델 ID"}</div>
            <div className="flex flex-col items-start gap-2">
              <code className="text-gray-200 break-all">{nativeId(model.id)}</code>
              <CopyButton text={nativeId(model.id)} label={lang === "en" ? "Copy model ID" : "모델 ID 복사"} />
            </div>
            <div className="text-gray-500 pt-1">{lang === "en" ? "Endpoint" : "엔드포인트"}</div>
            <code className="text-gray-300 break-all">{ch.endpoint}</code>
            <div className="text-gray-500 pt-1">{lang === "en" ? "Region" : "리전"}</div>
            <div className="text-gray-300">{ch.region}</div>
          </div>
          <div className="min-w-0 bg-gray-950/50 border border-gray-800 rounded-md p-3 space-y-1.5">
            <div className="text-gray-500">{lang === "en" ? "Pricing (per 1M tokens)" : "토큰 단가 (1M 기준)"}</div>
            {price ? (
              <div className="text-gray-200 tabular-nums">
                {lang === "en" ? "Input" : "입력"} <span className="font-semibold">{formatUnitPrice(price.input)}</span>
                {" / "}{lang === "en" ? "Output" : "출력"} <span className="font-semibold">{formatUnitPrice(price.output)}</span>
              </div>
            ) : (
              <div className="text-gray-500">{lang === "en" ? "Pricing unavailable" : "단가 정보 없음"}</div>
            )}
            <div className="text-gray-500 pt-2">{lang === "en" ? "Links" : "연결 링크"}</div>
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

        {/* 코드 예제 */}
        <div>
          <div className="flex flex-wrap items-start justify-between gap-3 mb-2">
            <h3 className="text-sm font-semibold text-gray-200">
              {lang === "en" ? "Code Examples" : "코드 예제"}
            </h3>
            <CopyButton text={examples[tab].code} label={lang === "en" ? "Copy code example" : "코드 예제 복사"} />
          </div>
          {/* API 종류 탭 — Converse / InvokeModel / Messages / Responses */}
          <div role="tablist" aria-label={lang === "en" ? "Code example API" : "코드 예제 API"} className="flex flex-wrap gap-1 mb-2">
            {examples.map((ex, i) => (
              <button
                key={ex.api}
                ref={(element) => { tabRefs.current[i] = element; }}
                type="button"
                role="tab"
                id={`${tabsId}-${i}`}
                aria-controls={`${tabsId}-panel`}
                aria-selected={tab === i}
                tabIndex={tab === i ? 0 : -1}
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
                className={tab === i ? "ui-button-primary" : "ui-button"}
              >
                {ex.api}
              </button>
            ))}
          </div>
          <div role="tabpanel" id={`${tabsId}-panel`} aria-labelledby={`${tabsId}-${tab}`} className="min-w-0">
            {/* 선택된 API가 의미하는 바 */}
            <p className="text-xs text-gray-400 leading-relaxed mb-2 bg-blue-500/10 border border-blue-500/20 rounded-md p-2.5">
              <span className="font-semibold text-gray-200">{examples[tab].api}</span>
              {" — "}
              {examples[tab].description}
            </p>
            <div className="text-[11px] text-gray-500 mb-1">{examples[tab].label}</div>
            <pre tabIndex={0} aria-label={lang === "en" ? `${examples[tab].api} code example` : `${examples[tab].api} 코드 예제`}
                 className="bg-gray-950 border border-gray-800 rounded-md p-3 overflow-x-auto text-xs text-gray-200 leading-relaxed">
              <code>{examples[tab].code}</code>
            </pre>
          </div>
        </div>
    </Dialog>
  );
}

export default function ModelExplorer() {
  const { lang } = useLang();
  const t = useT();
  const resource = useAsyncResource<ModelInfo[]>("model-catalog", fetchModels);
  const pricing = useAsyncResource<PricingResponse>("pricing", fetchPricing);
  const prices = pricing.data?.models ?? null;
  const priceOf = (id: string): PricingModelPrice | null =>
    prices && Object.prototype.hasOwnProperty.call(prices, id) ? prices[id] : null;
  const [search, setSearch] = useState("");
  const [channel, setChannel] = useState<ChannelType | "all">("all");
  const [selected, setSelected] = useState<ModelInfo | null>(null);

  const models = useMemo(() => sortResults(
    (resource.data ?? []).filter((model) => !isExcludedModel(model.name))
      .map((model) => ({ ...model, model_name: model.name })),
  ).map(({ id, name }) => ({ id, name })), [resource.data]);
  const resetFilters = () => { setSearch(""); setChannel("all"); };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return models.filter((m) => {
      if (channel !== "all" && channelOf(m.id).type !== channel) return false;
      if (q && !m.name.toLowerCase().includes(q) && !m.id.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [models, search, channel]);

  return (
    <div className="p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-100">
            {lang === "en" ? "Model Explorer" : "모델 탐색"}
          </h1>
          <p className="text-sm text-gray-500 mt-1">
            {lang === "en"
              ? "Select a model for invoke IDs, code examples, and links."
              : "모델을 선택하면 호출 ID·코드 예제·연결 링크를 볼 수 있습니다."}
          </p>
        </div>
        <RefreshControls
          refreshing={resource.refreshing || pricing.refreshing}
          onRefresh={() => { void resource.refresh(); void pricing.refresh(); }}
          updatedAt={resource.updatedAt}
        />
      </div>

      {/* 검색 + 채널 필터 */}
      <div className="flex items-end gap-3 flex-wrap">
        <label className="flex w-full flex-col gap-2 sm:w-64">
          <span className="text-xs font-medium text-gray-400">{lang === "en" ? "Search models" : "모델 검색"}</span>
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={lang === "en" ? "Model name or ID" : "모델 이름 또는 ID"}
            className="ui-input w-full"
          />
        </label>
        <div role="group" aria-label={lang === "en" ? "Channel filter" : "채널 필터"} className="flex gap-1 flex-wrap">
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
        <button type="button" onClick={resetFilters} disabled={search === "" && channel === "all"} className="ui-button">
          {t.common.resetFilters}
        </button>
        {resource.data !== null && (
          <span aria-live="polite" aria-atomic="true" className="self-center text-xs text-gray-500">
            {lang === "en" ? `${filtered.length} / ${models.length} models` : `모델 ${filtered.length} / ${models.length}개`}
          </span>
        )}
      </div>

      <DataError error={resource.error} resource={lang === "en" ? "model catalog" : "모델 카탈로그"}
                 onRetry={resource.refresh} hasData={models.length > 0} />
      <DataError error={pricing.error} resource={lang === "en" ? "unit prices" : "비용 단가"}
                 onRetry={pricing.refresh} hasData={prices !== null} />
      {resource.loading && <DataLoading />}
      {!resource.error && resource.data !== null && models.length === 0 && (
        <DataEmpty title={lang === "en" ? "No models available." : "등록된 모델이 없습니다."}
                   description={lang === "en" ? "The catalog is empty. Refresh to check for newly registered models." : "카탈로그가 비어 있습니다. 새로고침으로 모델 등록 여부를 확인하세요."} />
      )}
      {!resource.error && models.length > 0 && filtered.length === 0 && (
        <DataEmpty title={lang === "en" ? "No models match these filters." : "검색 조건에 맞는 모델이 없습니다."}
                   description={lang === "en" ? "Change your search or reset the filters to see all models." : "검색어를 바꾸거나 필터를 초기화하면 전체 모델을 볼 수 있습니다."} />
      )}

      {/* 카드 그리드 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {filtered.map((m) => {
          const ch = channelOf(m.id);
          const price = priceOf(m.id);
          return (
            <button
              key={m.id}
              type="button"
              onClick={() => setSelected(m)}
              aria-label={m.name}
              aria-haspopup="dialog"
              aria-expanded={selected?.id === m.id}
              className="w-full min-w-0 text-left bg-gray-900/50 border border-gray-800 rounded-xl p-4 hover:border-blue-500/50 focus-visible:border-blue-500/50 transition-colors group"
            >
              <div className="flex items-start justify-between gap-2">
                <h3 className="text-sm font-semibold text-gray-100 group-hover:text-blue-300 group-focus-visible:text-blue-300 transition-colors">
                  {m.name}
                </h3>
                <span className={`shrink-0 px-2 py-0.5 text-[11px] font-medium rounded-full border ${CHANNEL_BADGE[ch.type]}`}>
                  {ch.type === "bedrock" ? (m.id.startsWith("global.") ? "Global" : "US") : ch.type === "anthropic-cp" ? "CP" : ch.type === "openai-1p" ? "1P" : ch.region}
                </span>
              </div>
              <code className="block text-[11px] text-gray-500 break-all mt-1.5">{m.id}</code>
              <div className="text-[11px] text-gray-500 mt-2 tabular-nums">
                {price
                  ? `${formatPricePair(price)} ${lang === "en" ? "(per 1M tokens, in/out)" : "(1M 토큰당 입력/출력)"}`
                  : pricing.loading ? (lang === "en" ? "Loading prices…" : "단가 불러오는 중…")
                    : (lang === "en" ? "Pricing unavailable" : "단가 정보 없음")}
              </div>
            </button>
          );
        })}
      </div>

      {selected && <DetailModal key={selected.id} model={selected} price={priceOf(selected.id)} onClose={() => setSelected(null)} />}
    </div>
  );
}
