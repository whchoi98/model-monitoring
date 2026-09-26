"use client";

// 비용 단가 (v2.30.0) — GET /api/pricing 단일 출처. 제공사 섹션, 행 순서, 각주 번호는 응답 그대로 쓴다.
// 공식 단가는 12시간마다 자동 확인되고, 면책 문구는 상단 안내 상자와 참고 자료 끝에 두 번 표기한다.

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchPricing, pricingExportUrl } from "@/lib/api";
import { formatDateTime } from "@/lib/format";
import { useLang } from "@/lib/i18n-context";
import {
  TIER_LABELS, formatPricePair, notesForTier, tierBadges,
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
const CELL = "border-b border-gray-800/60 px-2 py-2.5 align-top";
const STICKY = "sticky left-0 z-10 bg-gray-900";
const BADGE_CLASS: Record<PricingBadge["kind"], string> = {
  unverified: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  pending: "border-sky-500/40 bg-sky-500/10 text-sky-300",
  promo: "border-purple-500/40 bg-purple-500/10 text-purple-300",
  promo_check: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

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

function Badges({ badges }: { badges: PricingBadge[] }) {
  if (badges.length === 0) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {badges.map((badge) => (
        <span
          key={badge.kind}
          data-badge={badge.kind}
          title={badge.title}
          className={`rounded border px-1.5 py-0.5 text-[10px] font-medium leading-tight ${BADGE_CLASS[badge.kind]}`}
        >
          {badge.label}
          <span className="sr-only">, {badge.title}</span>
        </span>
      ))}
    </div>
  );
}

function TierCell({ family, tierKey, lang, today, onFootnote }: {
  family: PricingFamily;
  tierKey: PricingTierKey;
  lang: Lang;
  today: Date;
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
            <span className="whitespace-nowrap tabular-nums text-gray-100" title={entry.model_ids.join("\n")}>
              {formatPricePair(entry)}
            </span>
            {"regions" in entry && <>{" "}<span className="text-gray-400">{entry.regions.join(", ")}</span></>}
            <Footnotes numbers={entry.footnotes} lang={lang} onFootnote={onFootnote} />
            <Badges badges={tierBadges(entry, notes, lang, today)} />
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
      className={`scroll-mt-36 rounded-lg px-2 py-1.5 transition-colors ${highlighted ? "bg-blue-500/15 ring-1 ring-blue-500/40" : ""}`}
    >
      <span className="mr-1.5 tabular-nums text-gray-500">[{reference.n}]</span>
      {reference.kind === "manual_note" && (
        <span className="mr-1.5 rounded border border-purple-500/40 bg-purple-500/10 px-1.5 py-0.5 text-[10px] font-medium text-purple-300">
          {lang === "en" ? "Manual note" : "수동 메모"}
        </span>
      )}
      {reference.url ? (
        <a href={reference.url} target="_blank" rel="noopener noreferrer" className="break-words text-blue-400 hover:underline">
          {title}<span aria-hidden="true"> ↗</span>
        </a>
      ) : (
        <span className="break-words text-gray-300">{title}</span>
      )}
      {reference.as_of && (
        <span className="text-gray-500">, {lang === "en" ? "checked" : "확인일"} {reference.as_of}</span>
      )}
    </li>
  );
}

/** Everything below the page heading once /api/pricing has answered — pure, so vitest renders it statically. */
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
  return (
    <>
      <div
        role="note"
        aria-label={L("Disclaimer", "면책 안내")}
        data-disclaimer="top"
        className="rounded-xl border border-amber-500/50 bg-amber-500/10 p-4 text-sm leading-relaxed text-amber-200"
      >
        <p>{data.disclaimer[lang]}</p>
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {OFFICIAL_LINKS.map((link) => (
            <a key={link.url} href={link.url} target="_blank" rel="noopener noreferrer" className="font-medium underline hover:no-underline">
              {L(link.en, link.ko)}<span aria-hidden="true"> ↗</span>
            </a>
          ))}
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs text-gray-400" data-last-sync>
          {sync && syncStatus ? (
            <>
              {L("Last automatic check", "마지막 자동 확인")}:{" "}
              {sync.finished_at ? (
                <time dateTime={sync.finished_at} className="tabular-nums text-gray-300">{formatDateTime(sync.finished_at, lang)}</time>
              ) : (
                <span className="text-gray-300">{L("in progress", "진행 중")}</span>
              )}
              , {L(syncStatus.en, syncStatus.ko)}
            </>
          ) : (
            L("No automatic check has run yet, initial values are shown.", "자동 확인 기록이 아직 없어 초기값을 표시합니다.")
          )}
          {data.pending_review > 0 && (
            <>
              {" "}
              <span className="sr-only">, </span>
              <span data-pending-count className="ml-3 rounded border border-sky-500/40 bg-sky-500/10 px-1.5 py-0.5 text-sky-300">
                {L(`${data.pending_review} pending review`, `검토 대기 ${data.pending_review}건`)}
              </span>
            </>
          )}
        </p>
        <div role="group" aria-label={L("Download price list", "가격표 내려받기")} className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-gray-400">{L("Download", "내려받기")}</span>
          {EXPORTS.map((item) => (
            <a key={item.format} href={pricingExportUrl(item.format, lang)} download className="ui-button">
              {item.label}
            </a>
          ))}
        </div>
      </div>

      {data.families.length === 0 && (
        <DataEmpty
          title={L("No unit prices yet.", "표시할 단가가 없습니다.")}
          description={L("No active channel has a price yet. Refresh after the next automatic check.", "활성 채널의 단가가 아직 없습니다. 다음 자동 확인 뒤 새로고침하세요.")}
        />
      )}

      {providerSections(data.families).map((section) => {
        const label = PROVIDER_LABELS[section.provider];
        return (
          <section key={section.provider} aria-labelledby={`pricing-${section.provider}`} className="min-w-0 rounded-xl border border-gray-800 bg-gray-900 p-4">
            <h2 id={`pricing-${section.provider}`} className="mb-3 text-sm font-semibold text-gray-200">{label}</h2>
            {/* relative: sr-only 텍스트(absolute)가 스크롤 영역 밖으로 빠져 페이지 가로 스크롤을 만들지 않게 한다. */}
            <div role="region" aria-label={L(`${label} price table`, `${label} 단가 표`)} tabIndex={0} data-pricing-scroll className="relative overflow-x-auto">
              <table className="w-full min-w-[760px] border-separate border-spacing-0 text-xs">
                <thead>
                  <tr className="text-gray-500">
                    <th scope="col" className={`${STICKY} border-b border-gray-800 py-2 pr-3 text-left font-medium`}>{L("Model", "모델")}</th>
                    {TIER_KEYS.map((key) => (
                      <th key={key} scope="col" className="border-b border-gray-800 px-2 py-2 text-left font-medium">{TIER_LABELS[key]}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {section.families.map((family) => (
                    <tr key={family.family_key} data-family={family.family_key}>
                      <th scope="row" className={`${STICKY} ${CELL} whitespace-nowrap pl-0 pr-3 text-left font-semibold text-gray-200`}>
                        {family.family}
                      </th>
                      {TIER_KEYS.map((key) => (
                        <TierCell key={key} family={family} tierKey={key} lang={lang} today={today} onFootnote={onFootnote} />
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        );
      })}

      <section aria-labelledby="pricing-notes-title" className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <h2 id="pricing-notes-title" className="mb-2 text-sm font-semibold text-gray-200">{L("Notes", "참고 사항")}</h2>
        <ol className="list-decimal space-y-1 pl-5 text-xs leading-relaxed text-gray-400">
          {NOTES.map((note) => <li key={note.en}>{L(note.en, note.ko)}</li>)}
        </ol>
      </section>

      <section aria-labelledby="pricing-references-title" className="rounded-xl border border-gray-800 bg-gray-900/50 p-4">
        <h2 id="pricing-references-title" className="mb-2 text-sm font-semibold text-gray-200">{L("References", "참고 자료")}</h2>
        <ol className="space-y-0.5 text-xs leading-relaxed">
          {data.references.map((reference) => (
            <ReferenceItem key={reference.id} reference={reference} lang={lang} highlighted={highlight === reference.n} />
          ))}
        </ol>
        <p data-disclaimer="bottom" className="mt-4 border-t border-gray-800 pt-3 text-xs leading-relaxed text-amber-300">
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
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-gray-100">{L("Unit Prices", "비용 단가")}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {L(
              "Per-model token prices (USD per 1M tokens), checked against official sources every 12 hours.",
              "모델별 토큰 단가(USD, 1M 토큰당)를 공식 출처에서 12시간마다 자동으로 확인해 보여 줍니다.",
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
