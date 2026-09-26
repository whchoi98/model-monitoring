"use client";

// 비용 단가 (v2.30.0) — GET /api/pricing 단일 출처. 제공사 섹션, 행 순서, 각주 번호는 응답 그대로 쓴다.
// 공식 단가는 12시간마다 자동 동기화되고, 면책 문구는 상단 안내 상자와 참고 자료 끝에 두 번 표기한다.
// 배지 설명과 모델 ID는 title 툴팁에만 두지 않는다(터치, 키보드 사용자가 볼 수 없다). 배지 설명은 배지 옆 글자로,
// 모델 ID는 "모델 ID 보기" 토글로 보여 준다. 폰에서는 표만 가로로 스크롤되므로 표 위 안내와 오른쪽 가장자리 흐림으로 알린다.
// 한글 문장은 break-keep(어절 단위 줄바꿈), 리전 id, 날짜, 가격 쌍, 배지, 각주는 토큰 중간에서 줄이 바뀌지 않는다.
// 세 제공사 표는 같은 고정 열 폭(table-fixed)이라 데스크톱에서 열 위치가 같다.

import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { fetchPricing, pricingExportUrl } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useLang } from "@/lib/i18n-context";
import {
  TIER_LABELS, formatPricePair, notesForTier, textRuns, tierBadges,
  type PricingBadge, type PricingTierKey,
} from "@/lib/pricingTable";
import type {
  PricingFamily, PricingInRegionTier, PricingReference, PricingResponse, PricingTier,
} from "@/lib/types";
import { useAsyncResource } from "@/hooks/useAsyncResource";
import { DataEmpty, DataError, DataLoading } from "./DataState";
import RefreshControls from "./RefreshControls";

type Lang = "ko" | "en";

const HIGHLIGHT_MS = 1500;
const TIER_KEYS: PricingTierKey[] = ["cp", "global", "us", "in_region"];
const PROVIDER_LABELS: Record<PricingFamily["provider"], string> = {
  anthropic: "Anthropic Claude",
  amazon: "Amazon Nova",
  openai: "OpenAI",
};
const EXPORTS: { format: "csv" | "md" | "json"; label: string }[] = [
  { format: "csv", label: "CSV" },
  { format: "md", label: "Markdown" },
  { format: "json", label: "JSON" },
];
const OFFICIAL_LINKS: { url: string; en: string; ko: string }[] = [
  { url: "https://aws.amazon.com/bedrock/pricing/", en: "Amazon Bedrock pricing", ko: "Amazon Bedrock 요금" },
  { url: "https://platform.claude.com/docs/en/about-claude/pricing", en: "Anthropic pricing", ko: "Anthropic 요금" },
];
const SYNC_STATUS: Record<string, { en: string; ko: string }> = {
  completed: { en: "completed", ko: "완료" },
  partial: { en: "partial, some sources failed", ko: "일부 출처 실패" },
  failed: { en: "failed", ko: "실패" },
  running: { en: "running", ko: "진행 중" },
};
const NOTES: { en: string; ko: string }[] = [
  { en: "Prices are in USD per 1M tokens, Standard tier input and output", ko: "단가는 USD, 1M 토큰당, Standard 등급 입력과 출력 기준이다" },
  { en: "Global channel prices can differ from the same model's US and In-Region channels", ko: "Global 채널 단가는 같은 모델의 US, In-Region 채널과 다를 수 있다" },
  { en: "OpenAI prices apply to inputs of 272K tokens or less", ko: "OpenAI는 입력 272K 이하 기준이다" },
  { en: "Cache, batch, long-context and priority prices are not included", ko: "캐시, batch, long-context, priority 단가는 포함하지 않는다" },
  { en: "The cost pages use the price in effect at each probe's time", ko: "비용 화면은 각 프로브 시각의 단가로 계산한다" },
];
const UNIT = { en: "input / output, USD per 1M tokens", ko: "입력 / 출력, 1M 토큰당 USD" };
// Korean prose wraps between words; a token too long for its line may still break anywhere instead of overflowing.
const PROSE = "break-keep [overflow-wrap:anywhere]";
const CELL = "border-b border-gray-800/60 px-2 py-2.5 align-top break-keep";
// Opaque in both themes (gray-900 is the card color) with a divider, so scrolled price fragments never touch the name.
const STICKY = "sticky left-0 z-10 border-r border-r-gray-800 bg-gray-900";
// The same fixed widths in every provider table: the model column, then four equal price columns.
const TABLE = "w-full min-w-[800px] table-fixed border-separate border-spacing-0 text-xs";
const MODEL_COL = "w-36";
const PRICE_COL = "w-[calc((100%_-_9rem)/4)]";
const BADGE_CLASS: Record<PricingBadge["kind"], string> = {
  unverified: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  pending: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  promo: "border-purple-500/40 bg-purple-500/10 text-purple-300",
  promo_check: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};
// Short labels never wrap. Promotion labels are longer than a phone-width column in English, so they wrap only between
// words (their date stays whole).
const BADGE_WRAP: Record<PricingBadge["kind"], string> = {
  unverified: "whitespace-nowrap",
  pending: "whitespace-nowrap",
  promo: "break-keep",
  promo_check: "break-keep",
};

/** Text whose price pairs and hyphenated tokens never wrap inside; `tail` (a footnote, "↗") stays with the last word. */
function Runs({ text, tail }: { text: string; tail?: ReactNode }) {
  const runs = textRuns(text, tail !== undefined);
  // textRuns makes the last word a nowrap run whenever it can; otherwise (empty text) the tail simply follows.
  const glueAt = runs.length > 0 && runs[runs.length - 1].nowrap ? runs.length - 1 : -1;
  return (
    <>
      {runs.map((run, i) => (run.nowrap
        ? <span key={i} className="whitespace-nowrap">{run.text}{i === glueAt && tail}</span>
        : <Fragment key={i}>{run.text}</Fragment>))}
      {glueAt === -1 && tail}
    </>
  );
}

/** Consecutive runs of the same provider, in response order (the backend already sorted them). */
export function providerSections(families: PricingFamily[]): { provider: PricingFamily["provider"]; families: PricingFamily[] }[] {
  const sections: { provider: PricingFamily["provider"]; families: PricingFamily[] }[] = [];
  for (const family of families) {
    const last = sections[sections.length - 1];
    if (last && last.provider === family.provider) last.families.push(family);
    else sections.push({ provider: family.provider, families: [family] });
  }
  return sections;
}

export type TableScrollCue = { overflow: boolean; scrolled: boolean; moreRight: boolean };

/**
 * Horizontal scroll state of a price table: `overflow` (wider than its box), `scrolled` (moved off the left edge)
 * and `moreRight` (columns still hidden on the right). A 1 px tolerance absorbs fractional widths.
 */
export function tableScrollCue(scrollLeft: number, clientWidth: number, scrollWidth: number): TableScrollCue {
  const overflow = scrollWidth - clientWidth > 1;
  return { overflow, scrolled: scrollLeft > 0, moreRight: overflow && scrollLeft + clientWidth < scrollWidth - 1 };
}

/** Re-reads the cue on scroll and on resize. A callback ref, so it also starts once the box mounts later. */
function useTableScrollCue() {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [cue, setCue] = useState<TableScrollCue>({ overflow: false, scrolled: false, moreRight: false });
  useEffect(() => {
    if (!box) return;
    const update = () => {
      const next = tableScrollCue(box.scrollLeft, box.clientWidth, box.scrollWidth);
      setCue((prev) => (prev.overflow === next.overflow && prev.scrolled === next.scrolled && prev.moreRight === next.moreRight
        ? prev : next));
    };
    update();
    box.addEventListener("scroll", update, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(box);
    if (box.firstElementChild) observer?.observe(box.firstElementChild);
    return () => {
      box.removeEventListener("scroll", update);
      observer?.disconnect();
    };
  }, [box]);
  return { ref: setBox, cue };
}

/**
 * The scrolling box of one provider table. On a phone the first visible price column is Claude Platform on AWS, so a
 * row can look empty ("—") while its prices sit off screen. A hint above the table (hidden once scrolled, space kept
 * so the table does not jump) and a fade on the right edge say there is more.
 */
function PriceTableScroll({ label, lang, children }: { label: string; lang: Lang; children: ReactNode }) {
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const { ref, cue } = useTableScrollCue();
  return (
    <>
      {cue.overflow && (
        <p aria-hidden="true" data-scroll-hint className={`mb-2 text-[11px] text-gray-500 ${PROSE} ${cue.scrolled ? "invisible" : ""}`}>
          → <Runs text={L("Scroll the table sideways for Global, US and In-Region prices", "표를 옆으로 스크롤하면 Global, US, In-Region 단가가 보입니다")} />
        </p>
      )}
      <div className="relative">
        {/* relative: sr-only 텍스트(absolute)가 스크롤 영역 밖으로 빠져 페이지 가로 스크롤을 만들지 않게 한다. */}
        <div ref={ref} role="region" aria-label={L(`${label} price table`, `${label} 단가 표`)} tabIndex={0} data-pricing-scroll className="relative overflow-x-auto">
          {children}
        </div>
        {cue.moreRight && (
          <div aria-hidden="true" data-scroll-fade className="pointer-events-none absolute inset-y-0 right-0 w-8 bg-gradient-to-l from-gray-900 to-transparent" />
        )}
      </div>
    </>
  );
}

function Footnotes({ numbers, lang, onFootnote }: { numbers: number[]; lang: Lang; onFootnote: (n: number) => void }) {
  return (
    <>
      {numbers.map((n) => (
        <sup key={n} className="ml-0.5">
          <a
            href={`#ref-${n}`}
            onClick={() => onFootnote(n)}
            aria-label={lang === "en" ? `Reference ${n}` : `참고 자료 ${n}`}
            className="text-[10px] font-medium text-blue-400 hover:underline"
          >
            [{n}]
          </a>
        </sup>
      ))}
    </>
  );
}

function Badges({ badges, lang, refNumbers, onFootnote }: {
  badges: PricingBadge[];
  lang: Lang;
  refNumbers: ReadonlyMap<string, number>;
  onFootnote: (n: number) => void;
}) {
  if (badges.length === 0) return null;
  return (
    <div className="mt-1 space-y-1">
      {badges.map((badge) => {
        const n = badge.ref === undefined ? undefined : refNumbers.get(badge.ref);
        return (
          <div key={badge.kind} className="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5">
            <span
              data-badge={badge.kind}
              className={`min-w-0 rounded border px-1.5 py-0.5 text-[10px] font-medium leading-tight ${BADGE_WRAP[badge.kind]} ${BADGE_CLASS[badge.kind]}`}
            >
              <Runs text={badge.label} />
            </span>
            <span className="sr-only">, </span>
            <span data-badge-detail={badge.kind} className="min-w-0 break-keep text-[10px] leading-tight text-gray-400">
              <span className="tabular-nums">
                <Runs text={badge.detail} tail={n === undefined ? undefined : <Footnotes numbers={[n]} lang={lang} onFootnote={onFootnote} />} />
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** One price line: the pair, then (In-Region) its regions. The footnote stays with the last token, each region whole. */
function PriceLine({ entry, lang, onFootnote }: {
  entry: PricingTier | PricingInRegionTier;
  lang: Lang;
  onFootnote: (n: number) => void;
}) {
  const regions = "regions" in entry ? entry.regions : [];
  const footnotes = <Footnotes numbers={entry.footnotes} lang={lang} onFootnote={onFootnote} />;
  return (
    <>
      <span className="whitespace-nowrap">
        <span className="tabular-nums text-gray-100" title={entry.model_ids.join("\n")}>{formatPricePair(entry)}</span>
        {regions.length === 0 && footnotes}
      </span>
      {regions.length > 0 && (
        <>
          {" "}
          <span data-regions className="text-gray-400">
            {regions.map((region, i) => (
              <Fragment key={region}>
                {i > 0 && ", "}
                <span className="whitespace-nowrap">{region}{i === regions.length - 1 && footnotes}</span>
              </Fragment>
            ))}
          </span>
        </>
      )}
    </>
  );
}

function TierCell({ family, tierKey, lang, today, refNumbers, showModelIds, onFootnote }: {
  family: PricingFamily;
  tierKey: PricingTierKey;
  lang: Lang;
  today: Date;
  refNumbers: ReadonlyMap<string, number>;
  showModelIds: boolean;
  onFootnote: (n: number) => void;
}) {
  const single = tierKey === "in_region" ? null : family.tiers[tierKey];
  const entries: (PricingTier | PricingInRegionTier)[] = tierKey === "in_region"
    ? family.tiers.in_region
    : single ? [single] : [];
  if (entries.length === 0) {
    return (
      <td data-tier={tierKey} className={CELL}>
        <span aria-hidden="true" className="text-gray-600">—</span>
        <span className="sr-only">{lang === "en" ? "No price" : "단가 없음"}</span>
      </td>
    );
  }
  const notes = notesForTier(family.notes, tierKey);
  return (
    <td data-tier={tierKey} className={CELL}>
      <div className="space-y-2">
        {entries.map((entry) => (
          <div key={entry.model_ids.join(" ")} data-price-line>
            <PriceLine entry={entry} lang={lang} onFootnote={onFootnote} />
            {showModelIds && (
              <span data-model-ids className="mt-0.5 block break-all font-mono text-[10px] leading-snug text-gray-500">
                {entry.model_ids.map((id) => <span key={id} className="block">{id}</span>)}
              </span>
            )}
            <Badges badges={tierBadges(entry, notes, lang, today)} lang={lang} refNumbers={refNumbers} onFootnote={onFootnote} />
          </div>
        ))}
      </div>
    </td>
  );
}

function ReferenceItem({ reference, lang, highlighted }: { reference: PricingReference; lang: Lang; highlighted: boolean }) {
  const title = lang === "en" ? reference.title_en : reference.title_ko;
  return (
    <li
      id={`ref-${reference.n}`}
      data-kind={reference.kind}
      data-highlighted={highlighted ? "true" : "false"}
      className={`scroll-mt-36 grid grid-cols-[2.75rem_1fr] rounded-lg px-2 py-1.5 transition-colors ${highlighted ? "bg-blue-500/15 ring-1 ring-blue-500/40" : ""}`}
    >
      <span className="whitespace-nowrap text-right pr-2 tabular-nums text-gray-500">[{reference.n}]</span>
      <span>
      {reference.url ? (
        <a href={reference.url} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
          <Runs text={title} tail={<span aria-hidden="true"> ↗</span>} />
        </a>
      ) : (
        <span className="text-gray-300"><Runs text={title} /></span>
      )}
      {reference.as_of && (
        <span className="text-gray-500">
          , <span className="whitespace-nowrap">{lang === "en" ? "checked" : "확인일"} {reference.as_of}</span>
        </span>
      )}
      </span>
    </li>
  );
}

/**
 * Everything below the page heading once /api/pricing has answered. No fetching, so vitest renders it statically
 * (the model-ID toggle starts off and the scroll cue starts hidden until the browser measures the table).
 */
export function PricingContent({ data, lang, today, highlight, onFootnote }: {
  data: PricingResponse;
  lang: Lang;
  today: Date;
  highlight: number | null;
  onFootnote: (n: number) => void;
}) {
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const sync = data.last_sync;
  const syncStatus = sync ? SYNC_STATUS[sync.status] ?? { en: sync.status, ko: sync.status } : null;
  const [showModelIds, setShowModelIds] = useState(false);
  const refNumbers = useMemo(() => new Map(data.references.map((reference) => [reference.id, reference.n])), [data.references]);
  return (
    <>
      <div
        role="note"
        aria-label={L("Disclaimer", "면책 안내")}
        data-disclaimer="top"
        className={`rounded-xl border border-amber-500/50 bg-amber-500/10 p-4 text-sm leading-relaxed text-amber-200 ${PROSE}`}
      >
        <p>{data.disclaimer[lang]}</p>
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {OFFICIAL_LINKS.map((link) => (
            <a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer" className="whitespace-nowrap font-medium underline hover:no-underline">
              {L(link.en, link.ko)}<span aria-hidden="true"> ↗</span>
            </a>
          ))}
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 break-keep text-xs text-gray-400" data-last-sync>
          <span>
            {sync && syncStatus ? (
              <>
                {L("Last official price sync", "마지막 공식 단가 동기화")}:{" "}
                {sync.finished_at ? (
                  <time dateTime={sync.finished_at} className="whitespace-nowrap tabular-nums text-gray-300">{formatDateTime(sync.finished_at, lang)}</time>
                ) : (
                  <span className="text-gray-300">{L("in progress", "진행 중")}</span>
                )}
                , {L(syncStatus.en, syncStatus.ko)}
              </>
            ) : (
              L("No official price sync has run yet, initial values are shown.", "공식 단가 동기화 기록이 아직 없어 초기값을 표시합니다.")
            )}
          </span>
          {data.pending_review > 0 && (
            <>
              <span className="sr-only">, </span>
              <span data-pending-count className="whitespace-nowrap rounded border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-sky-300">
                {L(`${data.pending_review} pending review`, `검토 대기 ${data.pending_review}건`)}
              </span>
            </>
          )}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            aria-pressed={showModelIds}
            onClick={() => setShowModelIds((value) => !value)}
            data-model-ids-toggle
            className={showModelIds ? "ui-button-primary" : "ui-button"}
          >
            {L("Show model IDs", "모델 ID 보기")}
          </button>
          <div role="group" aria-label={L("Download price list", "가격표 내려받기")} className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-gray-400">{L("Download", "내려받기")}</span>
            {EXPORTS.map((item) => (
              <a key={item.format} href={pricingExportUrl(item.format, lang)} download className="ui-button">
                {item.label}
              </a>
            ))}
          </div>
        </div>
      </div>

      {data.families.length === 0 && (
        <DataEmpty
          title={L("No unit prices yet.", "표시할 단가가 없습니다.")}
          description={L("No active channel has a price yet. Refresh after the next price sync.", "활성 채널의 단가가 아직 없습니다. 다음 단가 동기화 뒤 새로고침하세요.")}
        />
      )}

      {data.families.length > 0 && (
        <p data-unit-legend className="break-keep text-xs text-gray-400">
          {L("Each price cell", "각 단가 셀")}:{" "}
          <span className="whitespace-nowrap font-medium text-gray-300">{L("input / output", "입력 / 출력")}</span>,{" "}
          <span className="whitespace-nowrap font-medium text-gray-300">{L("USD per 1M tokens", "1M 토큰당 USD")}</span>
        </p>
      )}

      {providerSections(data.families).map((section) => {
        const label = PROVIDER_LABELS[section.provider];
        return (
          <section key={section.provider} aria-labelledby={`pricing-${section.provider}`} className="min-w-0 rounded-xl border border-gray-800 bg-gray-900 p-4">
            <h2 id={`pricing-${section.provider}`} className="mb-3 break-keep text-sm font-semibold text-gray-200">{label}</h2>
            <PriceTableScroll label={label} lang={lang}>
              <table className={TABLE}>
                <caption className="sr-only">{L(`${label} prices (${UNIT.en})`, `${label} 단가 (${UNIT.ko})`)}</caption>
                <colgroup>
                  <col className={MODEL_COL} />
                  {TIER_KEYS.map((key) => <col key={key} className={PRICE_COL} />)}
                </colgroup>
                <thead>
                  <tr className="text-gray-500">
                    <th scope="col" className={`${STICKY} border-b border-gray-800 py-2 pr-3 text-left align-bottom font-medium`}>{L("Model", "모델")}</th>
                    {TIER_KEYS.map((key) => (
                      <th key={key} scope="col" className="break-keep border-b border-gray-800 px-2 py-2 text-left align-bottom font-medium">
                        <Runs text={TIER_LABELS[key]} />
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {section.families.map((family) => (
                    <tr key={family.family_key} data-family={family.family_key}>
                      <th scope="row" className={`${STICKY} ${CELL} pl-0 pr-3 text-left font-semibold text-gray-200`}>
                        <Runs text={family.family} />
                      </th>
                      {TIER_KEYS.map((key) => (
                        <TierCell
                          key={key} family={family} tierKey={key} lang={lang} today={today}
                          refNumbers={refNumbers} showModelIds={showModelIds} onFootnote={onFootnote}
                        />
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </PriceTableScroll>
          </section>
        );
      })}

      <section aria-labelledby="pricing-notes-title" className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <h2 id="pricing-notes-title" className="mb-2 break-keep text-sm font-semibold text-gray-200">{L("Notes", "참고 사항")}</h2>
        <ol className={`list-decimal space-y-1 pl-5 text-xs leading-relaxed text-gray-400 ${PROSE}`}>
          {NOTES.map((note) => <li key={note.en}><Runs text={L(note.en, note.ko)} /></li>)}
        </ol>
      </section>

      <section aria-labelledby="pricing-references-title" className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <h2 id="pricing-references-title" className="mb-2 break-keep text-sm font-semibold text-gray-200">{L("References", "참고 자료")}</h2>
        <ol className={`space-y-0.5 text-xs leading-relaxed ${PROSE}`}>
          {data.references.map((reference) => (
            <ReferenceItem key={reference.id} reference={reference} lang={lang} highlighted={highlight === reference.n} />
          ))}
        </ol>
        <p data-disclaimer="bottom" className={`mt-4 border-t border-gray-800 pt-3 text-xs leading-relaxed text-amber-300 ${PROSE}`}>
          {data.disclaimer[lang]}
        </p>
      </section>
    </>
  );
}

export default function PricingPanel() {
  const { lang } = useLang();
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const resource = useAsyncResource<PricingResponse>("pricing", fetchPricing);
  const [highlight, setHighlight] = useState<number | null>(null);
  const highlightTimer = useRef<number | undefined>(undefined);

  // The anchor's own hash navigation scrolls to #ref-n; this only adds the 1.5 s highlight.
  const onFootnote = useCallback((n: number) => {
    window.clearTimeout(highlightTimer.current);
    setHighlight(n);
    highlightTimer.current = window.setTimeout(() => setHighlight(null), HIGHLIGHT_MS);
  }, []);
  useEffect(() => () => window.clearTimeout(highlightTimer.current), []);

  return (
    <div className="min-w-0 p-4 sm:p-6 space-y-4 sm:space-y-6 max-w-7xl mx-auto">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div className="min-w-0 break-keep">
          <h1 className="text-2xl font-bold text-gray-100">{L("Unit Prices", "비용 단가")}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {L(
              "Per-model token prices (USD per 1M tokens), synced with official sources every 12 hours.",
              "모델별 토큰 단가(USD, 1M 토큰당)를 12시간마다 공식 출처와 동기화해 보여 줍니다.",
            )}
          </p>
        </div>
        <RefreshControls refreshing={resource.refreshing} onRefresh={() => void resource.refresh()} updatedAt={resource.updatedAt} />
      </div>

      <DataError error={resource.error} resource={L("unit prices", "비용 단가")} onRetry={() => void resource.refresh()} hasData={resource.data !== null} />
      {resource.loading && <DataLoading />}
      {resource.data && (
        <PricingContent data={resource.data} lang={lang} today={new Date()} highlight={highlight} onFootnote={onFootnote} />
      )}
    </div>
  );
}
