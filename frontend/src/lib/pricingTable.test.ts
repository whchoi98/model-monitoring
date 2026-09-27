/**
 * 비용 단가 표 순수 로직 (v2.30.0, v2.31.0) — 열 이름(`tierLabel`, `headerParts`), 제공사별 열(`PROVIDER_COLUMNS`),
 * 화면 포맷(소수 둘째 자리부터 여섯째 자리까지), 캐시와 긴 컨텍스트 항목, 줄바꿈 단위(`textRuns`), 배지 판정,
 * `costFromPrices`.
 *
 * 정렬과 각주 번호는 백엔드가 정하므로 여기서는 검사하지 않는다. 배지 규칙: stale, seed_only → "자동 확인 안 됨",
 * pending → "검토 대기"(바뀐 항목만), 프로모션 메모 → 프로모션(날짜가 지나면 확인 필요, 각주는 메모의 source_id).
 */
import { afterEach, describe, expect, test, vi } from "vitest";
import { fetchPricing, pricingExportUrl } from "./api";
import type { PricingModelPrice, PricingNote, PricingPending, PricingTier } from "./types";
import {
  PROVIDER_COLUMNS, cacheItems, costFromPrices, formatPricePair, formatUnitPrice, headerParts, longItems,
  notesForTier, pendingDetail, textRuns, tierBadges, tierLabel, utcDate,
} from "./pricingTable";

afterEach(() => {
  vi.unstubAllGlobals();
});

// GPT 5.6 Sol in-region (us-east-1), the 2026-09-27 official values.
function tier(overrides: Partial<PricingTier> = {}): PricingTier {
  return {
    input: 4.4, output: 22, cache_read: 0.44, cache_write: 5.5, cache_write_1h: null,
    long: { input: 8.8, output: 33, cache_read: 0.88, cache_write: 11 },
    model_ids: ["openai:us-east-1:openai.gpt-5.6-sol"],
    source_ids: ["offer:offer-e2esol56"], footnotes: [6],
    verification: "verified", observed_at: "2026-09-26T15:00:00Z", pending: null,
    ...overrides,
  };
}

/** A pending row with the tier's own values, then `overrides` (so a test names only what changed). */
function pendingOf(base: PricingTier, overrides: Partial<PricingPending> = {}): PricingPending {
  const { input, output, cache_read, cache_write, cache_write_1h, long } = base;
  return { id: 91, observed_at: "2026-09-26T15:00:00Z", input, output, cache_read, cache_write, cache_write_1h, long, ...overrides };
}

// pricing_sources.PRICE_NOTES (v2.31.0): the promotion is cited from the OpenAI pricing page.
const SOL_PROMO: PricingNote = {
  family_key: "gpt-5.6-sol", kind: "promo", min_until: "2026-11-21",
  prior_price: {
    openai_list: { input: 5, output: 30 }, global: { input: 5, output: 30 }, in_region: { input: 5.5, output: 33 },
  },
  text_ko: "프로모션 단가다. OpenAI 공식 요금 문서에 최소 2026-11-21까지 적용한다고 기재돼 있다.",
  text_en: "Promotional price. The OpenAI pricing page states that it applies at least through 2026-11-21.",
  source: "openai_doc",
  source_id: "openai-pricing",
};

// A manual note (still supported): its footnote is the backend's note:<family_key> reference.
const MANUAL_PROMO: PricingNote = {
  ...SOL_PROMO, prior_price: { in_region: { input: 5.5, output: 33 } }, source: "manual_note", source_id: "note:gpt-5.6-sol",
};

const SEPT_26 = new Date("2026-09-26T12:00:00Z");

describe("tierLabel / headerParts / PROVIDER_COLUMNS — 열 이름과 제공사별 열", () => {
  test("열 이름은 KO와 EN이 같고 OpenAI 공식 가격만 번역한다", () => {
    expect((["cp", "openai_list", "global", "us", "in_region"] as const).map((key) => tierLabel(key, "ko"))).toEqual([
      "Claude Platform on AWS", "OpenAI 공식 가격", "AWS Bedrock - Global CRIS", "AWS Bedrock - US CRIS", "AWS Bedrock - In Region",
    ]);
    expect((["cp", "openai_list", "global", "us", "in_region"] as const).map((key) => tierLabel(key, "en"))).toEqual([
      "Claude Platform on AWS", "OpenAI official price", "AWS Bedrock - Global CRIS", "AWS Bedrock - US CRIS", "AWS Bedrock - In Region",
    ]);
  });

  test("머리글은 ' - ' 뒤에서만 줄이 바뀐다", () => {
    expect(headerParts("AWS Bedrock - Global CRIS")).toEqual(["AWS Bedrock -", "Global CRIS"]);
    expect(headerParts("AWS Bedrock - In Region")).toEqual(["AWS Bedrock -", "In Region"]);
    expect(headerParts("Claude Platform on AWS")).toEqual(["Claude Platform on AWS"]);
    expect(headerParts("OpenAI 공식 가격")).toEqual(["OpenAI 공식 가격"]);
  });

  test("제공사별 열: Anthropic은 Claude Platform on AWS, OpenAI는 OpenAI 공식 가격, Nova는 빈 첫 열", () => {
    expect(PROVIDER_COLUMNS).toEqual({
      anthropic: ["cp", "global", "us", "in_region"],
      openai: ["openai_list", "global", "us", "in_region"],
      amazon: [null, "global", "us", "in_region"],
    });
    // Every table has the same number of price columns, so the three tables line up.
    expect(new Set(Object.values(PROVIDER_COLUMNS).map((columns) => columns.length))).toEqual(new Set([4]));
  });
});

describe("formatUnitPrice / formatPricePair — 소수 둘째 자리부터, 여섯째 자리까지", () => {
  test.each([
    [0.06, "$0.06"], [4, "$4.00"], [4.4, "$4.40"], [0.1, "$0.10"], [16.5, "$16.50"], [2.75, "$2.75"], [0.33, "$0.33"],
    [12.5, "$12.50"], [82.5, "$82.50"], [1.375, "$1.375"], [6.875, "$6.875"], [0.0825, "$0.0825"], [0.011, "$0.011"],
    [0.1375, "$0.1375"], [0, "$0.00"], [4.4000000000000004, "$4.40"], [0.0000001, "$0.00"],
  ])("%s → %s", (value, expected) => {
    expect(formatUnitPrice(value)).toBe(expected);
  });

  test("입력 / 출력 쌍", () => {
    expect(formatPricePair({ input: 4, output: 20 })).toBe("$4.00 / $20.00");
    expect(formatPricePair(tier())).toBe("$4.40 / $22.00");
    expect(formatPricePair({ input: 0.33, output: 2.75 })).toBe("$0.33 / $2.75");
  });

  test("모델 탐색 단가(소수 둘째 자리 이내)는 v2.30.0 표시 그대로다", () => {
    expect(formatUnitPrice(4.4)).toBe("$4.40");
    expect(formatUnitPrice(0.11)).toBe("$0.11");
    expect(formatPricePair({ input: 0.11, output: 0.55 })).toBe("$0.11 / $0.55");
    expect(formatPricePair({ input: 12.34, output: 56.78 })).toBe("$12.34 / $56.78");
  });
});

describe("cacheItems / longItems — 둘째 줄(프롬프트 캐싱), GPT 셋째 줄(긴 컨텍스트)", () => {
  const opusGlobal = tier({ input: 4, output: 20, cache_read: 0.2, cache_write: 5, cache_write_1h: 8, long: null });

  test("Claude: 캐시 읽기, 쓰기(5분), 1시간 쓰기", () => {
    expect(cacheItems(opusGlobal, "ko")).toEqual([
      { label: "캐시 읽기", value: "$0.20" }, { label: "쓰기", value: "$5.00" }, { label: "1시간 쓰기", value: "$8.00" },
    ]);
    expect(cacheItems(opusGlobal, "en")).toEqual([
      { label: "Cache read", value: "$0.20" }, { label: "write", value: "$5.00" }, { label: "1h write", value: "$8.00" },
    ]);
    expect(longItems(opusGlobal, "ko")).toEqual([]);
  });

  test("출처에 있는 항목만, 0은 값이다 (Nova 캐시 쓰기 $0.00)", () => {
    expect(cacheItems(tier({ cache_read: 0.0825, cache_write: 0, cache_write_1h: null, long: null }), "ko")).toEqual([
      { label: "캐시 읽기", value: "$0.0825" }, { label: "쓰기", value: "$0.00" },
    ]);
    expect(cacheItems(tier({ cache_read: 0.275, cache_write: null, cache_write_1h: null }), "en")).toEqual([
      { label: "Cache read", value: "$0.275" },
    ]);
    expect(cacheItems(tier({ cache_read: null, cache_write: null, cache_write_1h: null }), "ko")).toEqual([]);
  });

  test("GPT 긴 컨텍스트: 입력 / 출력 쌍, 캐시 읽기, 쓰기", () => {
    const astraGlobal = tier({ input: 10, output: 50, cache_read: 1, cache_write: 12.5, long: { input: 20, output: 75, cache_read: 2, cache_write: 25 } });
    expect(longItems(astraGlobal, "ko")).toEqual([
      { label: "긴 컨텍스트", value: "$20.00 / $75.00" }, { label: "캐시 읽기", value: "$2.00" }, { label: "쓰기", value: "$25.00" },
    ]);
    expect(longItems(astraGlobal, "en")).toEqual([
      { label: "Long context", value: "$20.00 / $75.00" }, { label: "cache read", value: "$2.00" }, { label: "write", value: "$25.00" },
    ]);
    // GPT 5.4 has no long-context cache write.
    expect(longItems(tier({ long: { input: 5.5, output: 24.75, cache_read: 0.55, cache_write: null } }), "ko")).toEqual([
      { label: "긴 컨텍스트", value: "$5.50 / $24.75" }, { label: "캐시 읽기", value: "$0.55" },
    ]);
  });

  test("아직 새 필드를 보내지 않는 백엔드(undefined)는 항목이 없다", () => {
    const legacy = { input: 4, output: 20 } as unknown as PricingTier;
    expect(cacheItems(legacy, "ko")).toEqual([]);
    expect(longItems(legacy, "ko")).toEqual([]);
  });
});

describe("pendingDetail — 새 값은 바뀐 항목만", () => {
  test("입력이나 출력이 바뀌면 쌍", () => {
    const base = tier();
    const pending = { ...base, pending: pendingOf(base, { input: 5.5, output: 33 }) };
    expect(pendingDetail(pending, "ko")).toBe("새 값 $5.50 / $33.00");
    expect(pendingDetail(pending, "en")).toBe("New value $5.50 / $33.00");
  });

  test("쌍, 바뀐 캐시 항목, 긴 컨텍스트 순서", () => {
    const base = tier();
    const pending = {
      ...base,
      pending: pendingOf(base, { input: 5.5, output: 33, cache_write: 6.875, long: { input: 11, output: 49.5, cache_read: 1.1, cache_write: 13.75 } }),
    };
    expect(pendingDetail(pending, "ko")).toBe("새 값 $5.50 / $33.00, 쓰기 $6.875, 긴 컨텍스트 $11.00 / $49.50, 캐시 읽기 $1.10, 쓰기 $13.75");
    expect(pendingDetail(pending, "en")).toBe("New value $5.50 / $33.00, write $6.875, long context $11.00 / $49.50, cache read $1.10, write $13.75");
  });

  test("캐시만 바뀌면 캐시 항목만, 처음 생긴 값도 바뀐 항목이다", () => {
    const base = tier({ cache_write_1h: null });
    expect(pendingDetail({ ...base, pending: pendingOf(base, { cache_read: 0.5 }) }, "ko")).toBe("새 값 캐시 읽기 $0.50");
    // EN item labels start lower case after "New value" (the cache line itself says "Cache read").
    expect(pendingDetail({ ...base, pending: pendingOf(base, { cache_read: 0.5 }) }, "en")).toBe("New value cache read $0.50");
    expect(pendingDetail({ ...base, pending: pendingOf(base, { cache_write_1h: 8.8 }) }, "en")).toBe("New value 1h write $8.80");
  });

  test("긴 컨텍스트 값 하나만 바뀌어도 긴 컨텍스트 항목 전체", () => {
    const base = tier();
    const pending = { ...base, pending: pendingOf(base, { long: { input: 8.8, output: 33, cache_read: 0.9, cache_write: 11 } }) };
    expect(pendingDetail(pending, "ko")).toBe("새 값 긴 컨텍스트 $8.80 / $33.00, 캐시 읽기 $0.90, 쓰기 $11.00");
  });

  test("바뀐 항목이 없거나 없어지는 값뿐이면 쌍", () => {
    const base = tier();
    expect(pendingDetail({ ...base, pending: pendingOf(base) }, "ko")).toBe("새 값 $4.40 / $22.00");
    expect(pendingDetail({ ...base, pending: pendingOf(base, { cache_read: null }) }, "en")).toBe("New value $4.40 / $22.00");
  });

  test("검토 대기가 없으면 빈 문자열", () => {
    expect(pendingDetail(tier(), "ko")).toBe("");
  });
});

describe("textRuns — 토큰 중간에서 줄이 바뀌지 않게 나눈다", () => {
  const nowrap = (text: string, glueLast = false) => textRuns(text, glueLast).filter((run) => run.nowrap).map((run) => run.text);

  test("가격 쌍, 리전 id, ISO 날짜, offer id, 하이픈 토큰은 한 덩어리", () => {
    expect(nowrap("새 값 $3.00 / $18.00")).toEqual(["$3.00 / $18.00"]);
    expect(nowrap("새 값 $0.0825 / $2.75")).toEqual(["$0.0825 / $2.75"]);
    expect(nowrap("Global $5.00 / $30.00, US $5.50 / $33.00")).toEqual(["$5.00 / $30.00", "$5.50 / $33.00"]);
    expect(nowrap("프로모션(최소 2026-11-21까지)")).toEqual(["2026-11-21"]);
    expect(nowrap("Amazon Bedrock 약정 오퍼 요금표, offer-icq4574v6gz3i (Claude Fable 5.1)")).toEqual(["offer-icq4574v6gz3i"]);
    expect(nowrap("Global 채널 단가는 같은 모델의 US, In-Region 채널과 다를 수 있다")).toEqual(["In-Region"]);
    expect(nowrap("캐시, batch, long-context, priority 단가")).toEqual(["long-context"]);
  });

  test("이어 붙이면 원문 그대로다", () => {
    const text = "AWS Price List API, AmazonBedrock 사용 유형 USE1-Nova2.0Lite-input-tokens (Nova 2.0 Lite)";
    expect(textRuns(text).map((run) => run.text).join("")).toBe(text);
    expect(textRuns(text, true).map((run) => run.text).join("")).toBe(text);
    expect(textRuns("")).toEqual([]);
  });

  test("glueLast는 마지막 단어를 nowrap으로 떼어 각주가 붙게 한다", () => {
    expect(textRuns("프로모션 이전 단가 $5.50 / $33.00", true)).toEqual([
      { text: "프로모션 이전 단가 ", nowrap: false }, { text: "$5.50 / $33.00", nowrap: true },
    ]);
    expect(textRuns("Anthropic API 요금 (Claude Platform on AWS는 표준 요금)", true).slice(-2)).toEqual([
      { text: "Anthropic API 요금 (Claude Platform on AWS는 표준 ", nowrap: false }, { text: "요금)", nowrap: true },
    ]);
    expect(textRuns("초기값", true)).toEqual([{ text: "초기값", nowrap: true }]);
    expect(nowrap("단가 없음", false)).toEqual([]);
  });

  test("32자를 넘는 토큰은 nowrap으로 두지 않는다 (overflow-wrap:anywhere가 좁은 열 안에서 끊는다)", () => {
    const long = "aws-external-anthropic-us-east-2-api-endpoint-host";
    expect(nowrap(`endpoint ${long}`)).toEqual([]);
    expect(nowrap(`endpoint ${long}`, true)).toEqual([]);
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

  test("stale → 자동 확인 안 됨, 설명은 공식 출처 확인일", () => {
    const stale = tier({ verification: "stale", observed_at: "2026-09-20T03:00:00Z" });
    expect(tierBadges(stale, [], "ko", SEPT_26)).toEqual([
      { kind: "unverified", label: "자동 확인 안 됨", detail: "공식 출처 확인 2026-09-20" },
    ]);
    expect(tierBadges(stale, [], "en", SEPT_26)).toEqual([
      { kind: "unverified", label: "Not auto-verified", detail: "Confirmed at source 2026-09-20" },
    ]);
  });

  test("observed_at이 없는 stale → 초기값이 아니라 공식 출처 확인일 없음", () => {
    const stale = tier({ verification: "stale", observed_at: null });
    expect(tierBadges(stale, [], "ko", SEPT_26)).toEqual([
      { kind: "unverified", label: "자동 확인 안 됨", detail: "공식 출처 확인일 없음" },
    ]);
    expect(tierBadges(stale, [], "en", SEPT_26)[0].detail).toBe("No source confirmation date");
  });

  test("seed_only → 자동 확인 안 됨, 설명은 초기값", () => {
    const seed = tier({ verification: "seed_only", observed_at: null });
    expect(tierBadges(seed, [], "ko", SEPT_26)).toEqual([{ kind: "unverified", label: "자동 확인 안 됨", detail: "초기값" }]);
    expect(tierBadges(seed, [], "en", SEPT_26)[0].detail).toBe("Initial value");
  });

  test("none은 배지를 만들지 않는다", () => {
    expect(tierBadges(tier({ verification: "none" }), [], "ko", SEPT_26)).toEqual([]);
  });

  test("pending → 검토 대기, 설명은 pendingDetail", () => {
    const base = tier();
    const pending = { ...base, pending: pendingOf(base, { input: 3, output: 18 }) };
    expect(tierBadges(pending, [], "ko", SEPT_26)).toEqual([{ kind: "pending", label: "검토 대기", detail: "새 값 $3.00 / $18.00" }]);
    expect(tierBadges(pending, [], "en", SEPT_26)).toEqual([{ kind: "pending", label: "Pending review", detail: "New value $3.00 / $18.00" }]);
    const cacheOnly = { ...base, pending: pendingOf(base, { cache_read: 0.5 }) };
    expect(tierBadges(cacheOnly, [], "ko", SEPT_26)[0].detail).toBe("새 값 캐시 읽기 $0.50");
  });

  test("프로모션 메모 → 프로모션 배지, 설명은 프로모션 이전 단가, 각주는 메모의 출처(OpenAI 공식 요금 문서)", () => {
    const [badge] = tierBadges(tier(), notesForTier([SOL_PROMO], "in_region"), "ko", SEPT_26);
    expect(badge).toEqual({
      kind: "promo", label: "프로모션(최소 2026-11-21까지)",
      detail: "프로모션 이전 단가 $5.50 / $33.00", ref: "openai-pricing",
    });
    const [en] = tierBadges(tier(), notesForTier([SOL_PROMO], "global"), "en", SEPT_26);
    expect(en.label).toBe("Promotion (until at least 2026-11-21)");
    expect(en.detail).toBe("Price before the promotion $5.00 / $30.00");
    expect(en.ref).toBe(SOL_PROMO.source_id);
    const [list] = tierBadges(tier({ input: 4, output: 20 }), notesForTier([SOL_PROMO], "openai_list"), "ko", SEPT_26);
    expect(list.detail).toBe("프로모션 이전 단가 $5.00 / $30.00");
  });

  test("수동 메모의 각주는 note:<family_key> 참고 자료", () => {
    const [badge] = tierBadges(tier(), notesForTier([MANUAL_PROMO], "in_region"), "ko", SEPT_26);
    expect(badge.ref).toBe("note:gpt-5.6-sol");
  });

  test("프로모션 외 배지는 참고 자료 링크가 없다", () => {
    const base = tier({ verification: "stale", observed_at: "2026-09-20T03:00:00Z" });
    const stale = { ...base, pending: pendingOf(base, { input: 5.5, output: 33 }) };
    expect(tierBadges(stale, [], "ko", SEPT_26).map((b) => b.ref)).toEqual([undefined, undefined]);
  });

  test("티어를 좁히지 않은 메모는 열 이름과 함께 모든 이전 단가를 보여 준다", () => {
    const [badge] = tierBadges(tier(), [SOL_PROMO], "ko", SEPT_26);
    expect(badge.detail).toBe(
      "프로모션 이전 단가 OpenAI 공식 가격 $5.00 / $30.00, AWS Bedrock - Global CRIS $5.00 / $30.00, AWS Bedrock - In Region $5.50 / $33.00",
    );
    const [en] = tierBadges(tier(), [SOL_PROMO], "en", SEPT_26);
    expect(en.detail).toBe(
      "Price before the promotion OpenAI official price $5.00 / $30.00, AWS Bedrock - Global CRIS $5.00 / $30.00, AWS Bedrock - In Region $5.50 / $33.00",
    );
    // A tier key the frontend does not know stays as sent.
    const [unknown] = tierBadges(tier(), [{ ...SOL_PROMO, prior_price: { batch: { input: 1, output: 2 }, global: { input: 5, output: 30 } } }], "ko", SEPT_26);
    expect(unknown.detail).toBe("프로모션 이전 단가 batch $1.00 / $2.00, AWS Bedrock - Global CRIS $5.00 / $30.00");
  });

  test("min_until 당일(UTC)까지는 프로모션, 다음 날부터 종료 여부 확인 필요", () => {
    const notes = notesForTier([SOL_PROMO], "in_region");
    expect(tierBadges(tier(), notes, "ko", new Date("2026-11-21T23:59:59Z"))[0].kind).toBe("promo");
    const [passed] = tierBadges(tier(), notes, "ko", new Date("2026-11-22T00:00:00Z"));
    expect(passed.kind).toBe("promo_check");
    expect(passed.label).toBe("프로모션 종료 여부 확인 필요");
    expect(passed.detail).toBe("프로모션 이전 단가 $5.50 / $33.00");
    expect(passed.ref).toBe("openai-pricing");
    expect(tierBadges(tier(), notes, "en", new Date("2026-12-01T00:00:00Z"))[0].label).toBe("Check whether the promotion has ended");
  });

  test("배지 순서: 자동 확인 안 됨 → 검토 대기 → 프로모션", () => {
    const base = tier({ verification: "stale", observed_at: "2026-09-20T03:00:00Z" });
    const all = { ...base, pending: pendingOf(base, { input: 5.5, output: 33 }) };
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
    const [list] = notesForTier([SOL_PROMO], "openai_list");
    expect(list.prior_price).toEqual({ openai_list: { input: 5, output: 30 } });
    expect(list.source_id).toBe("openai-pricing");
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
