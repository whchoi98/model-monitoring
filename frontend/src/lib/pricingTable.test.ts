/**
 * 비용 단가 표 순수 로직 (v2.30.0) — 화면 포맷(소수 둘째 자리 고정), 배지 판정, `costFromPrices`.
 *
 * 정렬과 각주 번호는 백엔드가 정하므로 여기서는 검사하지 않는다. 배지 규칙은 설계서 UI 절:
 * stale, seed_only → "자동 확인 안 됨", pending → "검토 대기", 수동 메모 → 프로모션(날짜가 지나면 확인 필요).
 */
import { afterEach, describe, expect, test, vi } from "vitest";
import { fetchPricing, pricingExportUrl } from "./api";
import type { PricingModelPrice, PricingNote, PricingTier } from "./types";
import {
  costFromPrices, formatPricePair, formatUnitPrice, noteReferenceId, notesForTier, tierBadges, utcDate,
} from "./pricingTable";

afterEach(() => {
  vi.unstubAllGlobals();
});

function tier(overrides: Partial<PricingTier> = {}): PricingTier {
  return {
    input: 4.4, output: 22, model_ids: ["openai:us-east-1:openai.gpt-5.6-sol"],
    source_ids: ["offer:offer-e2esol56"], footnotes: [6],
    verification: "verified", observed_at: "2026-09-26T15:00:00Z", pending: null,
    ...overrides,
  };
}

const SOL_PROMO: PricingNote = {
  family_key: "gpt-5.6-sol", kind: "promo", min_until: "2026-11-21",
  prior_price: { in_region: { input: 5.5, output: 33 }, global: { input: 5, output: 30 } },
  text_ko: "2026-09-23 AWS 모델 카드 기재(현재 미게재), CHANGELOG v2.28.1",
  text_en: "Listed on the AWS model card on 2026-09-23 (no longer shown), CHANGELOG v2.28.1",
  source: "manual_note",
};

const SEPT_26 = new Date("2026-09-26T12:00:00Z");

describe("formatUnitPrice / formatPricePair — 화면은 소수 둘째 자리 고정", () => {
  test.each([
    [0.06, "$0.06"], [4, "$4.00"], [4.4, "$4.40"], [0.1, "$0.10"], [16.5, "$16.50"], [2.75, "$2.75"], [0.33, "$0.33"],
  ])("%s → %s", (value, expected) => {
    expect(formatUnitPrice(value)).toBe(expected);
  });

  test("입력 / 출력 쌍", () => {
    expect(formatPricePair({ input: 4, output: 20 })).toBe("$4.00 / $20.00");
    expect(formatPricePair(tier())).toBe("$4.40 / $22.00");
  });
});

describe("utcDate", () => {
  test("UTC 날짜만 남긴다, 오프셋 없는 값은 UTC로 읽는다", () => {
    expect(utcDate("2026-09-26T15:00:00Z")).toBe("2026-09-26");
    expect(utcDate("2026-09-26T23:30:00")).toBe("2026-09-26");
    expect(utcDate(null)).toBeNull();
    expect(utcDate("not a date")).toBeNull();
  });
});

describe("tierBadges", () => {
  test("verified이고 검토 대기와 메모가 없으면 배지가 없다", () => {
    expect(tierBadges(tier(), [], "ko", SEPT_26)).toEqual([]);
  });

  test("stale → 자동 확인 안 됨, 설명은 마지막 확인일", () => {
    const stale = tier({ verification: "stale", observed_at: "2026-09-20T03:00:00Z" });
    expect(tierBadges(stale, [], "ko", SEPT_26)).toEqual([
      { kind: "unverified", label: "자동 확인 안 됨", detail: "마지막 확인 2026-09-20" },
    ]);
    expect(tierBadges(stale, [], "en", SEPT_26)).toEqual([
      { kind: "unverified", label: "Not auto-verified", detail: "Last verified 2026-09-20" },
    ]);
  });

  test("observed_at이 없는 stale → 초기값이 아니라 마지막 확인일 없음", () => {
    const stale = tier({ verification: "stale", observed_at: null });
    expect(tierBadges(stale, [], "ko", SEPT_26)).toEqual([
      { kind: "unverified", label: "자동 확인 안 됨", detail: "마지막 확인일 없음" },
    ]);
    expect(tierBadges(stale, [], "en", SEPT_26)[0].detail).toBe("No confirmation date");
  });

  test("seed_only → 자동 확인 안 됨, 설명은 초기값", () => {
    const seed = tier({ verification: "seed_only", observed_at: null });
    expect(tierBadges(seed, [], "ko", SEPT_26)).toEqual([{ kind: "unverified", label: "자동 확인 안 됨", detail: "초기값" }]);
    expect(tierBadges(seed, [], "en", SEPT_26)[0].detail).toBe("Initial value");
  });

  test("none은 배지를 만들지 않는다", () => {
    expect(tierBadges(tier({ verification: "none" }), [], "ko", SEPT_26)).toEqual([]);
  });

  test("pending → 검토 대기, 설명은 새 값", () => {
    const pending = tier({ pending: { id: 91, input: 3, output: 18, observed_at: "2026-09-26T15:00:00Z" } });
    expect(tierBadges(pending, [], "ko", SEPT_26)).toEqual([{ kind: "pending", label: "검토 대기", detail: "새 값 $3.00 / $18.00" }]);
    expect(tierBadges(pending, [], "en", SEPT_26)).toEqual([{ kind: "pending", label: "Pending review", detail: "New value $3.00 / $18.00" }]);
  });

  test("수동 메모 → 프로모션 배지, 설명은 프로모션 이전 단가, 메모 근거는 참고 자료 각주", () => {
    const [badge] = tierBadges(tier(), notesForTier([SOL_PROMO], "in_region"), "ko", SEPT_26);
    expect(badge).toEqual({
      kind: "promo", label: "프로모션(최소 2026-11-21까지, 수동 메모)",
      detail: "프로모션 이전 단가 $5.50 / $33.00", ref: "note:gpt-5.6-sol",
    });
    const [en] = tierBadges(tier(), notesForTier([SOL_PROMO], "global"), "en", SEPT_26);
    expect(en.label).toBe("Promotion (until at least 2026-11-21, manual note)");
    expect(en.detail).toBe("Price before the promotion $5.00 / $30.00");
    expect(en.ref).toBe(noteReferenceId("gpt-5.6-sol"));
  });

  test("수동 메모 외 배지는 참고 자료 링크가 없다", () => {
    const stale = tier({ verification: "stale", observed_at: "2026-09-20T03:00:00Z",
      pending: { id: 7, input: 5.5, output: 33, observed_at: "2026-09-26T15:00:00Z" } });
    expect(tierBadges(stale, [], "ko", SEPT_26).map((b) => b.ref)).toEqual([undefined, undefined]);
  });

  test("티어를 좁히지 않은 메모는 티어 이름과 함께 모든 이전 단가를 보여 준다", () => {
    const [badge] = tierBadges(tier(), [SOL_PROMO], "ko", SEPT_26);
    expect(badge.detail).toBe("프로모션 이전 단가 In-Region $5.50 / $33.00, Global $5.00 / $30.00");
  });

  test("min_until 당일(UTC)까지는 프로모션, 다음 날부터 종료 여부 확인 필요", () => {
    const notes = notesForTier([SOL_PROMO], "in_region");
    expect(tierBadges(tier(), notes, "ko", new Date("2026-11-21T23:59:59Z"))[0].kind).toBe("promo");
    const [passed] = tierBadges(tier(), notes, "ko", new Date("2026-11-22T00:00:00Z"));
    expect(passed.kind).toBe("promo_check");
    expect(passed.label).toBe("프로모션 종료 여부 확인 필요");
    expect(passed.detail).toBe("프로모션 이전 단가 $5.50 / $33.00");
    expect(passed.ref).toBe("note:gpt-5.6-sol");
    expect(tierBadges(tier(), notes, "en", new Date("2026-12-01T00:00:00Z"))[0].label).toBe("Check whether the promotion has ended");
  });

  test("배지 순서: 자동 확인 안 됨 → 검토 대기 → 프로모션", () => {
    const all = tier({
      verification: "stale", observed_at: "2026-09-20T03:00:00Z",
      pending: { id: 7, input: 5.5, output: 33, observed_at: "2026-09-26T15:00:00Z" },
    });
    expect(tierBadges(all, notesForTier([SOL_PROMO], "in_region"), "ko", SEPT_26).map((b) => b.kind))
      .toEqual(["unverified", "pending", "promo"]);
  });
});

describe("notesForTier", () => {
  test("그 티어의 이전 단가가 있는 메모만 남기고 이전 단가를 그 티어로 좁힌다", () => {
    expect(notesForTier([SOL_PROMO], "us")).toEqual([]);
    expect(notesForTier([SOL_PROMO], "cp")).toEqual([]);
    const [global] = notesForTier([SOL_PROMO], "global");
    expect(global.prior_price).toEqual({ global: { input: 5, output: 30 } });
    expect(SOL_PROMO.prior_price).toHaveProperty("in_region"); // 원본은 바꾸지 않는다
  });
});

describe("costFromPrices", () => {
  const models: Record<string, PricingModelPrice> = {
    "openai:us-east-1:openai.gpt-6-sol": { input: 2.2, output: 11, verification: "verified" },
    "openai:global:global.openai.gpt-6-luna": { input: 0.1, output: 0.5, verification: "stale" },
    "us.amazon.nova-2-lite-v1:0": { input: 0.33, output: 2.75, verification: "seed_only" },
  };

  test("USD per 1M 토큰 산술", () => {
    expect(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", 1_000_000, 1_000_000)).toBeCloseTo(13.2, 9);
    expect(costFromPrices(models, "openai:global:global.openai.gpt-6-luna", 2_000_000, 500_000)).toBeCloseTo(0.45, 9);
    expect(costFromPrices(models, "us.amazon.nova-2-lite-v1:0", 32, 128)).toBeCloseTo((32 * 0.33 + 128 * 2.75) / 1e6, 12);
  });

  test("단가가 없으면 null — prefix fallback 없음", () => {
    expect(costFromPrices(models, "openai:us:us.openai.gpt-6-sol", 100, 100)).toBeNull();
    expect(costFromPrices(models, "openai:us-east-1:openai.gpt-6", 100, 100)).toBeNull();
    expect(costFromPrices(models, "toString", 100, 100)).toBeNull();
    expect(costFromPrices(null, "openai:us-east-1:openai.gpt-6-sol", 100, 100)).toBeNull();
    expect(costFromPrices(undefined, "openai:us-east-1:openai.gpt-6-sol", 100, 100)).toBeNull();
  });

  test("토큰 수가 없으면 0으로 센다 (백엔드 COALESCE와 같음)", () => {
    expect(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", null, 1000)).toBeCloseTo(0.011, 12);
    expect(costFromPrices(models, "openai:us-east-1:openai.gpt-6-sol", undefined, undefined)).toBe(0);
  });
});

describe("pricing API client", () => {
  test("pricingExportUrl — format과 lang을 쿼리로 싣는 같은 출처 경로", () => {
    expect(pricingExportUrl("csv", "ko")).toBe("/api/pricing/export?format=csv&lang=ko");
    expect(pricingExportUrl("md", "en")).toBe("/api/pricing/export?format=md&lang=en");
    expect(pricingExportUrl("json", "ko")).toBe("/api/pricing/export?format=json&lang=ko");
  });

  test("fetchPricing — 인증 없는 GET /api/pricing", async () => {
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify({ currency: "USD", families: [] }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(fetchPricing()).resolves.toMatchObject({ currency: "USD", families: [] });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/pricing");
    expect(new Headers(fetchMock.mock.calls[0][1]?.headers).has("Authorization")).toBe(false);
  });
});
