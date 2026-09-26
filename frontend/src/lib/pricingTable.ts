// 비용 단가 표(/pricing) 순수 로직 (v2.30.0) — 셀 포맷, 줄바꿈 단위, 배지 판정, /api/pricing `models`로 비용 계산.
// 정렬과 각주 번호는 백엔드(GET /api/pricing)가 정한다. 여기서는 다시 정렬하거나 번호를 매기지 않는다.

import { parseTimestamp } from "./format";
import type { PricingModelPrice, PricingNote, PricingTier } from "./types";

export type PricingTierKey = "cp" | "global" | "us" | "in_region";

export const TIER_LABELS: Record<PricingTierKey, string> = {
  cp: "Claude Platform on AWS",
  global: "Global",
  us: "US",
  in_region: "In-Region",
};

/** "$4.00" — the screen always shows two decimals; exports keep the backend's own number. */
export function formatUnitPrice(v: number): string {
  return `$${v.toFixed(2)}`;
}

/** "$4.00 / $20.00" (input / output). */
export function formatPricePair(t: { input: number; output: number }): string {
  return `${formatUnitPrice(t.input)} / ${formatUnitPrice(t.output)}`;
}

/** One run of display text; a `nowrap` run is rendered so a line never breaks inside it. */
export type TextRun = { text: string; nowrap: boolean };

// A price pair ("$4.00 / $20.00") or a hyphen-joined token (region id, ISO date, offer id, "In-Region"). Browsers break
// after a hyphen, so "us-east-2" can end up as "us-east-" and "2" without this.
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
 * touch or keyboard users. `ref` is the reference id whose footnote carries the full manual note (promotions only).
 */
export type PricingBadge = {
  kind: "unverified" | "pending" | "promo" | "promo_check";
  label: string;
  detail: string;
  ref?: string;
};

/** Reference id of a family's manual note, the same format as the backend's `pricing_sources.note_source_id`. */
export function noteReferenceId(familyKey: string): string {
  return `note:${familyKey}`;
}

/** Notes that name a prior price for this tier, narrowed to that tier's prior price only. */
export function notesForTier(notes: PricingNote[], tier: PricingTierKey): PricingNote[] {
  return notes
    .filter((note) => Object.prototype.hasOwnProperty.call(note.prior_price, tier))
    .map((note) => ({ ...note, prior_price: { [tier]: note.prior_price[tier] } }));
}

function priorPriceText(note: PricingNote): string {
  const entries = Object.entries(note.prior_price);
  if (entries.length === 1) return formatPricePair(entries[0][1]);
  return entries
    .map(([tier, price]) => `${TIER_LABELS[tier as PricingTierKey] ?? tier} ${formatPricePair(price)}`)
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
    const next = formatPricePair(tier.pending);
    badges.push({ kind: "pending", label: L("Pending review", "검토 대기"), detail: L(`New value ${next}`, `새 값 ${next}`) });
  }
  const todayUtc = today.toISOString().slice(0, 10);
  for (const note of notes) {
    if (note.kind !== "promo") continue;
    // The note's own text (its basis date) is the manual-note reference; the cell links to it instead of repeating it.
    const detail = `${L("Price before the promotion", "프로모션 이전 단가")} ${priorPriceText(note)}`;
    const ref = noteReferenceId(note.family_key);
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
