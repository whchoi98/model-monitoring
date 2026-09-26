// 비용 단가 표(/pricing) 순수 로직 (v2.30.0) — 셀 포맷, 배지 판정, /api/pricing `models`로 비용 계산.
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

/** UTC calendar date "YYYY-MM-DD" of an API timestamp (offset-less values are UTC), or null. */
export function utcDate(value: string | null | undefined): string | null {
  const timestamp = parseTimestamp(value);
  return timestamp === null ? null : new Date(timestamp).toISOString().slice(0, 10);
}

export type PricingBadge = { kind: "unverified" | "pending" | "promo" | "promo_check"; label: string; title: string };

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
    let title = L("Initial value", "초기값");
    if (tier.verification === "stale") {
      // A stale tier was verified once; without observed_at it has no date, but it is not an initial value either.
      const checked = utcDate(tier.observed_at);
      title = checked ? L(`Last verified ${checked}`, `마지막 확인 ${checked}`) : L("No confirmation date", "마지막 확인일 없음");
    }
    badges.push({ kind: "unverified", label: L("Not auto-verified", "자동 확인 안 됨"), title });
  }
  if (tier.pending) {
    const next = formatPricePair(tier.pending);
    badges.push({ kind: "pending", label: L("Pending review", "검토 대기"), title: L(`New value ${next}`, `새 값 ${next}`) });
  }
  const todayUtc = today.toISOString().slice(0, 10);
  for (const note of notes) {
    if (note.kind !== "promo") continue;
    const title = `${L("Price before the promotion", "프로모션 이전 단가")} ${priorPriceText(note)}\n${lang === "en" ? note.text_en : note.text_ko}`;
    badges.push(todayUtc > note.min_until
      ? { kind: "promo_check", label: L("Check whether the promotion has ended", "프로모션 종료 여부 확인 필요"), title }
      : {
        kind: "promo",
        label: L(`Promotion (until at least ${note.min_until}, manual note)`, `프로모션(최소 ${note.min_until}까지, 수동 메모)`),
        title,
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
