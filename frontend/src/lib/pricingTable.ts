// 비용 단가 표(/pricing) 순수 로직 (v2.30.0, v2.31.0) — 열 이름과 제공사별 열, 셀 포맷, 캐시와 긴 컨텍스트 항목,
// 줄바꿈 단위, 배지 판정, /api/pricing `models`로 비용 계산.
// 정렬과 각주 번호는 백엔드(GET /api/pricing)가 정한다. 여기서는 다시 정렬하거나 번호를 매기지 않는다.

import { parseTimestamp } from "./format";
import type { PricingFamily, PricingModelPrice, PricingNote, PricingPriceFields, PricingTier } from "./types";

export type PricingTierKey = "cp" | "openai_list" | "global" | "us" | "in_region";

const TIER_TITLES: Record<PricingTierKey, { ko: string; en: string }> = {
  cp: { ko: "Claude Platform on AWS", en: "Claude Platform on AWS" },
  openai_list: { ko: "OpenAI 공식 가격", en: "OpenAI official price" },
  global: { ko: "AWS Bedrock - Global CRIS", en: "AWS Bedrock - Global CRIS" },
  us: { ko: "AWS Bedrock - US CRIS", en: "AWS Bedrock - US CRIS" },
  in_region: { ko: "AWS Bedrock - In Region", en: "AWS Bedrock - In Region" },
};

/** Column title of a price tier (the same words in the Markdown export). */
export function tierLabel(key: PricingTierKey, lang: "ko" | "en"): string {
  return TIER_TITLES[key][lang];
}

/**
 * Price columns of each provider table, in display order. `null` is Amazon Nova's blank first column: its header
 * and cells stay empty so the three tables keep the same column positions.
 */
export const PROVIDER_COLUMNS: Record<PricingFamily["provider"], (PricingTierKey | null)[]> = {
  anthropic: ["cp", "global", "us", "in_region"],
  openai: ["openai_list", "global", "us", "in_region"],
  amazon: [null, "global", "us", "in_region"],
};

const DEFAULT_COLUMNS: (PricingTierKey | null)[] = [null, "global", "us", "in_region"];

/**
 * Price columns of a provider table. A provider the frontend does not know (a newer backend) gets the blank first
 * column and the three AWS Bedrock columns, so its table still lines up with the others instead of breaking the page.
 */
export function columnsFor(provider: string): (PricingTierKey | null)[] {
  return Object.prototype.hasOwnProperty.call(PROVIDER_COLUMNS, provider)
    ? PROVIDER_COLUMNS[provider as PricingFamily["provider"]]
    : DEFAULT_COLUMNS;
}

/** Header lines that never break inside: "AWS Bedrock - Global CRIS" -> ["AWS Bedrock -", "Global CRIS"]. */
export function headerParts(label: string): string[] {
  const at = label.indexOf(" - ");
  return at < 0 ? [label] : [label.slice(0, at + 2), label.slice(at + 3)];
}

/**
 * "$4.00" — two to six decimals, zeros past the second trimmed: 12.5 -> "$12.50", 1.375 -> "$1.375",
 * 0.0825 -> "$0.0825". Official prices have at most six decimals (the backend's PRICE_QUANTUM).
 * Never throws: NaN, ±Infinity and values of 1e21 or more (where toFixed gives "NaN" or exponent notation) are shown
 * as they are ("$NaN", "$1e+21", "$1.5e+30").
 */
export function formatUnitPrice(v: number): string {
  // toFixed switches to exponent notation at 1e21 ("1.5e+30"), which the fraction split below would truncate.
  if (!Number.isFinite(v) || Math.abs(v) >= 1e21) return `$${v}`;
  const [whole, fraction] = v.toFixed(6).split(".");
  return `$${whole}.${fraction.replace(/0+$/, "").padEnd(2, "0")}`;
}

/** "$4.00 / $20.00" (input / output). */
export function formatPricePair(t: { input: number; output: number }): string {
  return `${formatUnitPrice(t.input)} / ${formatUnitPrice(t.output)}`;
}

/** One labelled price of a cache or long-context line: "캐시 읽기" + "$0.20". */
export type PriceItem = { label: string; value: string };

// `!= null` also skips a field an older backend does not send yet (undefined), so the page never shows "$NaN".
function isSet(v: number | null | undefined): v is number {
  return v != null;
}

/** Prompt-caching prices of a cell, only those the source has: read, write (Claude 5-minute), 1h write (Claude). */
export function cacheItems(p: PricingPriceFields, lang: "ko" | "en"): PriceItem[] {
  const labels = lang === "en"
    ? { read: "Cache read", write: "write", write1h: "1h write" }
    : { read: "캐시 읽기", write: "쓰기", write1h: "1시간 쓰기" };
  const items: PriceItem[] = [];
  if (isSet(p.cache_read)) items.push({ label: labels.read, value: formatUnitPrice(p.cache_read) });
  if (isSet(p.cache_write)) items.push({ label: labels.write, value: formatUnitPrice(p.cache_write) });
  if (isSet(p.cache_write_1h)) items.push({ label: labels.write1h, value: formatUnitPrice(p.cache_write_1h) });
  return items;
}

/** GPT long-context prices: the input / output pair first, then its cache read and write. [] without `long`. */
export function longItems(p: PricingPriceFields, lang: "ko" | "en"): PriceItem[] {
  const long = p.long;
  if (!long) return [];
  const labels = lang === "en"
    ? { pair: "Long context", read: "cache read", write: "write" }
    : { pair: "긴 컨텍스트", read: "캐시 읽기", write: "쓰기" };
  const items: PriceItem[] = [{ label: labels.pair, value: formatPricePair(long) }];
  if (isSet(long.cache_read)) items.push({ label: labels.read, value: formatUnitPrice(long.cache_read) });
  if (isSet(long.cache_write)) items.push({ label: labels.write, value: formatUnitPrice(long.cache_write) });
  return items;
}

const CACHE_FIELDS = ["cache_read", "cache_write", "cache_write_1h"] as const;

function sameLong(a: PricingPriceFields["long"] | undefined, b: PricingPriceFields["long"] | undefined): boolean {
  if (!a || !b) return !a && !b;
  return a.input === b.input && a.output === b.output
    && (a.cache_read ?? null) === (b.cache_read ?? null) && (a.cache_write ?? null) === (b.cache_write ?? null);
}

/**
 * Pending badge detail: "새 값 " / "New value " + what the pending row changes — the input / output pair when either
 * differs, then the cache items that differ, then every long-context item when `long` differs. When nothing differs
 * (or only to a missing value), the pair. The items follow "New value" mid-sentence, so EN labels start lower case
 * ("New value cache read $0.50"). Without the cache read, the first cache item gets the cache noun the cell's cache
 * line takes from "캐시 읽기": "새 값 캐시 1시간 쓰기 $17.60", "New value cache write $11.00, 1h write $17.60". The
 * export's Markdown pending text uses the same rule.
 */
export function pendingDetail(tier: PricingTier, lang: "ko" | "en"): string {
  const prefix = lang === "en" ? "New value" : "새 값";
  const next = tier.pending;
  if (!next) return "";
  const phrase = (item: PriceItem) =>
    `${lang === "en" ? item.label.charAt(0).toLowerCase() + item.label.slice(1) : item.label} ${item.value}`;
  const parts: string[] = [];
  if (next.input !== tier.input || next.output !== tier.output) parts.push(formatPricePair(next));
  const changedCache: PricingPriceFields = { ...next, long: null };
  for (const field of CACHE_FIELDS) {
    if ((next[field] ?? null) === (tier[field] ?? null)) changedCache[field] = null;
  }
  const changed = cacheItems(changedCache, lang);
  if (changed.length > 0 && !isSet(changedCache.cache_read)) {
    changed[0] = { ...changed[0], label: `${lang === "en" ? "cache" : "캐시"} ${changed[0].label}` };
  }
  parts.push(...changed.map(phrase));
  if (!sameLong(next.long, tier.long)) parts.push(...longItems(next, lang).map(phrase));
  if (parts.length === 0) parts.push(formatPricePair(next));
  return `${prefix} ${parts.join(", ")}`;
}

/** One run of display text; a `nowrap` run is rendered so a line never breaks inside it. */
export type TextRun = { text: string; nowrap: boolean };

// A price pair ("$4.00 / $20.00") or a hyphen-joined token (region id, ISO date, offer id). Browsers break after a
// hyphen, so "us-east-2" can end up as "us-east-" and "2" without this.
const UNBREAKABLE = /\$\d+(?:\.\d+)? \/ \$\d+(?:\.\d+)?|[A-Za-z0-9.]+(?:-[A-Za-z0-9.]+)+/g;
// Longer tokens stay breakable, so the page's overflow-wrap:anywhere keeps them inside a narrow column.
const MAX_NOWRAP = 32;

/**
 * Splits text into runs so price pairs and hyphen-joined tokens never wrap mid-token. With `glueLast` the final word
 * becomes a `nowrap` run too, so a footnote or "↗" rendered right after it stays on its line.
 */
export function textRuns(text: string, glueLast = false): TextRun[] {
  const runs: TextRun[] = [];
  const pattern = new RegExp(UNBREAKABLE.source, "g");
  let at = 0;
  for (let match = pattern.exec(text); match !== null; match = pattern.exec(text)) {
    if (match[0].length > MAX_NOWRAP) continue;
    if (match.index > at) runs.push({ text: text.slice(at, match.index), nowrap: false });
    runs.push({ text: match[0], nowrap: true });
    at = match.index + match[0].length;
  }
  if (at < text.length) runs.push({ text: text.slice(at), nowrap: false });
  const last = runs[runs.length - 1];
  if (glueLast && last && !last.nowrap) {
    const word = /\S+$/.exec(last.text);
    if (word && word[0].length > MAX_NOWRAP) return runs;
    if (word && word.index > 0) {
      runs.splice(runs.length - 1, 1, { text: last.text.slice(0, word.index), nowrap: false }, { text: word[0], nowrap: true });
    } else if (word) {
      last.nowrap = true;
    }
  }
  return runs;
}

/** UTC calendar date "YYYY-MM-DD" of an API timestamp (offset-less values are UTC), or null. */
export function utcDate(value: string | null | undefined): string | null {
  const timestamp = parseTimestamp(value);
  return timestamp === null ? null : new Date(timestamp).toISOString().slice(0, 10);
}

/**
 * One badge of a price cell. `detail` is shown as text next to the badge, because a `title` tooltip never reaches
 * touch or keyboard users. `ref` is the reference id whose footnote carries the note's source (promotions only).
 */
export type PricingBadge = {
  kind: "unverified" | "pending" | "promo" | "promo_check";
  label: string;
  detail: string;
  ref?: string;
};

/** Notes that name a prior price for this tier, narrowed to that tier's prior price only. */
export function notesForTier(notes: PricingNote[], tier: PricingTierKey): PricingNote[] {
  return notes
    .filter((note) => Object.prototype.hasOwnProperty.call(note.prior_price, tier))
    .map((note) => ({ ...note, prior_price: { [tier]: note.prior_price[tier] } }));
}

function priorPriceText(note: PricingNote, lang: "ko" | "en"): string {
  const entries = Object.entries(note.prior_price);
  if (entries.length === 1) return formatPricePair(entries[0][1]);
  return entries
    .map(([tier, price]) => {
      const label = Object.prototype.hasOwnProperty.call(TIER_TITLES, tier) ? tierLabel(tier as PricingTierKey, lang) : tier;
      return `${label} ${formatPricePair(price)}`;
    })
    .join(", ");
}

/**
 * Badges for one price cell, in display order: not auto-verified, pending review, promotion.
 * A promotion whose `min_until` date (UTC) has passed turns into a "check whether it ended" badge.
 */
export function tierBadges(tier: PricingTier, notes: PricingNote[], lang: "ko" | "en", today: Date): PricingBadge[] {
  const L = (en: string, ko: string) => (lang === "en" ? en : ko);
  const badges: PricingBadge[] = [];
  if (tier.verification === "stale" || tier.verification === "seed_only") {
    let detail = L("Initial value", "초기값");
    if (tier.verification === "stale") {
      // A stale tier was verified once; without observed_at it has no date, but it is not an initial value either.
      const checked = utcDate(tier.observed_at);
      detail = checked
        ? L(`Confirmed at source ${checked}`, `공식 출처 확인 ${checked}`)
        : L("No source confirmation date", "공식 출처 확인일 없음");
    }
    badges.push({ kind: "unverified", label: L("Not auto-verified", "자동 확인 안 됨"), detail });
  }
  if (tier.pending) {
    badges.push({ kind: "pending", label: L("Pending review", "검토 대기"), detail: pendingDetail(tier, lang) });
  }
  const todayUtc = today.toISOString().slice(0, 10);
  for (const note of notes) {
    if (note.kind !== "promo") continue;
    // The note's own text is its source's reference (the OpenAI pricing page, or a manual note); the cell links to
    // that footnote instead of repeating it.
    const detail = `${L("Price before the promotion", "프로모션 이전 단가")} ${priorPriceText(note, lang)}`;
    const ref = note.source_id;
    badges.push(todayUtc > note.min_until
      ? { kind: "promo_check", label: L("Check whether the promotion has ended", "프로모션 종료 여부 확인 필요"), detail, ref }
      : {
        kind: "promo",
        label: L(`Promotion (until at least ${note.min_until})`, `프로모션(최소 ${note.min_until}까지)`),
        detail,
        ref,
      });
  }
  return badges;
}

/** USD for one call at the current price of `modelId`; null when the model has no price (shown as "—"). */
export function costFromPrices(
  models: Record<string, PricingModelPrice> | null | undefined,
  modelId: string,
  inputTokens: number | null | undefined,
  outputTokens: number | null | undefined,
): number | null {
  if (!models || !Object.prototype.hasOwnProperty.call(models, modelId)) return null;
  const price = models[modelId];
  // Missing token counts count as zero, like the backend's COALESCE(tokens, 0) row cost.
  return ((inputTokens ?? 0) * price.input + (outputTokens ?? 0) * price.output) / 1_000_000;
}
