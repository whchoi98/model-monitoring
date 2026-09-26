import type { Page } from "@playwright/test";
import type {
  PricingFamily, PricingModelPrice, PricingReference, PricingResponse, PricingTier,
} from "../src/lib/types";

export const modelCatalog = [
  { id: "anthropic-fable", name: "Anthropic Claude Fable 5.1 (US)" },
  { id: "global-fable", name: "Bedrock Claude Fable 5.1 (Global)" },
  { id: "us-fable", name: "Bedrock Claude Fable 5.1 (US)" },
  { id: "global-astra", name: "OpenAI GPT 6 Astra (Global)" },
  { id: "us-astra", name: "OpenAI GPT 6 Astra (US)" },
  { id: "regional-astra", name: "OpenAI GPT 6 Astra (us-west-2)" },
];

export function monitoringData() {
  const now = Date.now();
  const timestamp = (minutes: number) => new Date(now - minutes * 60_000).toISOString();
  const latest = modelCatalog.slice(0, 5).map((model, index) => ({
    id: index + 1, run_id: 42,
    model_id: model.id, model_name: model.name,
    timestamp: timestamp(index === 4 ? 45 : 2),
    status: index === 1 ? "error" : index === 2 ? "overloaded" : "success",
    ttft_ms: index === 1 || index === 2 ? null : 450 + index * 130,
    total_latency_ms: index === 1 || index === 2 ? null : 2000 + index * 250,
    server_latency_ms: null, input_tokens: 32, output_tokens: 128, tps: 62 + index,
    error_message: index === 1 ? "ServiceUnavailable: request failed" : index === 2 ? "Vendor overloaded" : null,
    iteration: 1, category: "chat-short",
  }));
  const trend = Array.from({ length: 10 }, (_, sample) => latest.map((result) => ({
    ...result,
    timestamp: timestamp(2 + sample * 5),
    ttft_ms: result.ttft_ms == null ? null : result.ttft_ms + sample * 20,
  }))).flat();
  return {
    latest, trend,
    status: {
      is_running: true, current_cycle_running: false, interval_seconds: 300,
      last_run_time: timestamp(2), next_run_time: timestamp(-3),
      last_completed_time: timestamp(2), expected_model_count: 6,
    },
    anomalies: {
      hours: 12, total_probes: 100, total_failures: 3,
      models: [{ model_name: modelCatalog[1].name, failures: 3, total: 20, last_error: "ServiceUnavailable" }],
    },
  };
}

export const categories = [
  { id: "chat-short", label_ko: "짧은 대화", label_en: "Short chat" },
  { id: "reasoning", label_ko: "추론", label_en: "Reasoning" },
  { id: "code-gen", label_ko: "코드 생성", label_en: "Code generation" },
  { id: "summarize", label_ko: "요약", label_en: "Summarize" },
  { id: "structured", label_ko: "JSON 추출", label_en: "Structured" },
  { id: "translate", label_ko: "번역", label_en: "Translate" },
];

// ── GET /api/pricing (v2.30.0) ─────────────────────────────────────────────
// Offer ids other than the three real ones quoted in the design (Opus 5.5, GPT 6 Astra, GPT 5.4) are
// synthetic. Offer tokens, legal-term links and presigned URLs never belong in a fixture.

const OFFER_API = "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html";
const PRICE_LIST_API = "https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_pricing_GetProducts.html";

function priceTier(input: number, output: number, model_ids: string[], source_id: string, footnote: number,
  overrides: Partial<PricingTier> = {}): PricingTier {
  return {
    input, output, model_ids, source_ids: [source_id], footnotes: [footnote],
    verification: "verified", observed_at: "2026-09-26T15:00:00Z", pending: null, ...overrides,
  };
}

const pricingFamilies: PricingFamily[] = [
  {
    family_key: "claude-fable-5-1", family: "Claude Fable 5.1", provider: "anthropic",
    tiers: {
      cp: priceTier(10, 50, ["anthropic:claude-fable-5-1"], "anthropic-pricing", 1),
      global: priceTier(10, 50, ["global.anthropic.claude-fable-5-1"], "offer:offer-e2efable51", 2),
      us: priceTier(11, 55, ["us.anthropic.claude-fable-5-1"], "offer:offer-e2efable51", 2,
        { verification: "stale", observed_at: "2026-09-20T03:00:00Z" }),
      in_region: [],
    },
    notes: [],
  },
  {
    family_key: "claude-opus-5-5", family: "Claude Opus 5.5", provider: "anthropic",
    tiers: {
      cp: priceTier(4, 20, ["anthropic:claude-opus-5-5"], "anthropic-pricing", 1),
      global: priceTier(4, 20, ["global.anthropic.claude-opus-5-5"], "offer:offer-7sp77cpl4rveu", 3),
      us: priceTier(4.4, 22, ["us.anthropic.claude-opus-5-5"], "offer:offer-7sp77cpl4rveu", 3),
      in_region: [],
    },
    notes: [],
  },
  {
    family_key: "nova-2-lite", family: "Nova 2.0 Lite", provider: "amazon",
    tiers: {
      cp: null, global: null,
      us: priceTier(0.33, 2.75, ["us.amazon.nova-2-lite-v1:0"], "pricelist:USE1-Nova2.0Lite-input-tokens", 4,
        { verification: "seed_only", observed_at: null }),
      in_region: [],
    },
    notes: [],
  },
  {
    family_key: "gpt-6-astra", family: "GPT 6 Astra", provider: "openai",
    tiers: {
      cp: null,
      global: priceTier(10, 50, ["openai:global:global.openai.gpt-6-astra"], "offer:offer-7epta7rbw5aws", 5),
      us: priceTier(11, 55, ["openai:us:us.openai.gpt-6-astra"], "offer:offer-7epta7rbw5aws", 5),
      in_region: [{ regions: ["us-west-2"], ...priceTier(11, 55, ["openai:us-west-2:openai.gpt-6-astra"], "offer:offer-7epta7rbw5aws", 5) }],
    },
    notes: [],
  },
  {
    family_key: "gpt-5.6-sol", family: "GPT 5.6 Sol", provider: "openai",
    tiers: {
      cp: null,
      global: priceTier(4, 20, ["openai:global:global.openai.gpt-5.6-sol"], "offer:offer-e2esol56", 6),
      us: null,
      in_region: [{
        regions: ["us-east-1", "us-east-2"],
        ...priceTier(4.4, 22, ["openai:us-east-1:openai.gpt-5.6-sol", "openai:us-east-2:openai.gpt-5.6-sol"], "offer:offer-e2esol56", 6),
      }],
    },
    notes: [{
      family_key: "gpt-5.6-sol", kind: "promo", min_until: "2026-11-21",
      prior_price: { in_region: { input: 5.5, output: 33 }, global: { input: 5, output: 30 } },
      text_ko: "2026-09-23 AWS 모델 카드 기재(현재 미게재), CHANGELOG v2.28.1",
      text_en: "Listed on the AWS model card on 2026-09-23 (no longer shown), CHANGELOG v2.28.1",
      source: "manual_note",
    }],
  },
  {
    // Production has one price for all three GPT 5.4 regions; the us-west-2 split is synthetic so the
    // e2e suite exercises a multi-line In-Region cell.
    family_key: "gpt-5.4", family: "GPT 5.4", provider: "openai",
    tiers: {
      cp: null, global: null, us: null,
      in_region: [
        {
          regions: ["us-east-1", "us-east-2"],
          ...priceTier(2.75, 16.5, ["openai:us-east-1:openai.gpt-5.4", "openai:us-east-2:openai.gpt-5.4"], "offer:offer-5l5a5izq5fbec", 7,
            { pending: { id: 91, input: 3, output: 18, observed_at: "2026-09-26T15:00:00Z" } }),
        },
        { regions: ["us-west-2"], ...priceTier(2.5, 15, ["openai:us-west-2:openai.gpt-5.4"], "offer:offer-5l5a5izq5fbec", 7) },
      ],
    },
    notes: [],
  },
];

function offerReference(n: number, offerId: string, model: string, as_of: string): PricingReference {
  return {
    n, id: `offer:${offerId}`, kind: "agreement_offer",
    title_en: `Amazon Bedrock agreement offer ${offerId}, ${model}`,
    title_ko: `Amazon Bedrock 계약 오퍼 ${offerId}, ${model}`,
    url: OFFER_API, as_of,
  };
}

const pricingReferences: PricingReference[] = [
  {
    n: 1, id: "anthropic-pricing", kind: "anthropic_doc",
    title_en: "Anthropic API pricing (Claude Platform on AWS uses standard pricing)",
    title_ko: "Anthropic API 요금 (Claude Platform on AWS는 표준 요금)",
    url: "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing", as_of: "2026-09-26",
  },
  offerReference(2, "offer-e2efable51", "Claude Fable 5.1", "2026-09-20"),
  offerReference(3, "offer-7sp77cpl4rveu", "Claude Opus 5.5", "2026-09-26"),
  {
    n: 4, id: "pricelist:USE1-Nova2.0Lite-input-tokens", kind: "price_list",
    title_en: "AWS Price List, USE1-Nova2.0Lite-input-tokens",
    title_ko: "AWS Price List, USE1-Nova2.0Lite-input-tokens",
    url: PRICE_LIST_API, as_of: "2026-09-26",
  },
  offerReference(5, "offer-7epta7rbw5aws", "GPT 6 Astra", "2026-09-26"),
  offerReference(6, "offer-e2esol56", "GPT 5.6 Sol", "2026-09-26"),
  offerReference(7, "offer-5l5a5izq5fbec", "GPT 5.4", "2026-09-26"),
  {
    n: 8, id: "official:bedrock-pricing", kind: "official_page",
    title_en: "Amazon Bedrock pricing", title_ko: "Amazon Bedrock 요금",
    url: "https://aws.amazon.com/bedrock/pricing/", as_of: null,
  },
  {
    n: 9, id: "official:model-card-openai-gpt-6-astra", kind: "official_page",
    title_en: "Amazon Bedrock model card, OpenAI GPT 6 Astra", title_ko: "Amazon Bedrock 모델 카드, OpenAI GPT 6 Astra",
    url: "https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-openai-gpt-6-astra.html", as_of: null,
  },
  {
    n: 10, id: "note:gpt-5.6-sol", kind: "manual_note",
    title_en: "GPT 5.6 Sol promotion until at least 2026-11-21, listed on the AWS model card on 2026-09-23 (no longer shown), CHANGELOG v2.28.1",
    title_ko: "GPT 5.6 Sol 프로모션 최소 2026-11-21까지, 2026-09-23 AWS 모델 카드 기재(현재 미게재), CHANGELOG v2.28.1",
    url: null, as_of: null,
  },
];

function pricingModels(families: PricingFamily[]): Record<string, PricingModelPrice> {
  const models: Record<string, PricingModelPrice> = {};
  for (const family of families) {
    const { cp, global, us, in_region } = family.tiers;
    for (const tier of [cp, global, us, ...in_region]) {
      if (!tier) continue;
      for (const id of tier.model_ids) models[id] = { input: tier.input, output: tier.output, verification: tier.verification };
    }
  }
  return models;
}

export const pricingFixture: PricingResponse = {
  currency: "USD",
  unit: "per_1m_tokens",
  generated_at: "2026-09-26T16:00:00Z",
  last_sync: { id: 12, started_at: "2026-09-26T15:00:00Z", finished_at: "2026-09-26T15:00:31Z", status: "completed" },
  pending_review: 1,
  families: pricingFamilies,
  models: pricingModels(pricingFamilies),
  references: pricingReferences,
  disclaimer: {
    ko: "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요.",
    en: "This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.",
  },
};

/** All API traffic stays in fixtures, including unexpected mutations. */
export async function mockApi(page: Page) {
  const data = monitoringData();
  await page.route("**/api/**", async (route) => {
    const url = new URL(route.request().url());
    const values: Record<string, unknown> = {
      "/api/models": modelCatalog,
      "/api/prompts": [],
      "/api/auto-probe/status": data.status,
      "/api/auto-probe/latest": data.latest,
      "/api/auto-probe/trend": data.trend,
      "/api/auto-probe/anomalies": data.anomalies,
      "/api/auto-probe/categories": categories,
      "/api/insights/latest": null,

    };
    const body = values[url.pathname];
    await route.fulfill({
      status: body === undefined ? 404 : 200,
      contentType: "application/json",
      body: JSON.stringify(body === undefined ? { detail: "Unmocked API request" } : body),
    });
  });
  return data;
}
