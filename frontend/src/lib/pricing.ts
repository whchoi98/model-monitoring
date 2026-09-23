// 모델별 토큰 단가 (USD per 1M tokens). Phase 2 Cost Dashboard에서도 재사용.
//
// 출처: AWS Bedrock public pricing(모델 카드) + Anthropic API pricing.
// 모델 카드가 아직 없는 신규 출시 모델은 Bedrock ListFoundationModelAgreementOffers의
// offer rate card를 출처로 쓰고, 카드가 게시되면 재대조한다 (예: GPT 6 Sol/Luna, ADR-028).
// 가격이 변동되면 이 파일과 backend/pricing.py를 함께 업데이트할 것 (PRICE_TABLE 동일 유지).
// "anthropic:*" prefix는 Claude Platform on AWS (vendor endpoint) - 동일 단가 가정.

export interface ModelPricing {
  /** USD per 1M input tokens */
  input: number;
  /** USD per 1M output tokens */
  output: number;
}

// Bedrock inference profile (global.* / us.*) 및 Anthropic CP on AWS (anthropic:*) 통합.
// 모델 ID prefix를 strip한 base 키로 lookup.
const PRICE_TABLE: Record<string, ModelPricing> = {
  // Anthropic Claude
  "claude-fable-5-1": { input: 10.0, output: 50.0 }, // Fable 5.1 — Fable 5와 동일 티어/단가 (v2.22.0)
  "claude-fable-5": { input: 10.0, output: 50.0 },
  // Opus 5.5 (v2.27.0) — Anthropic 정가 $4/$20. 정확 키가 없으면 prefix fallback이 claude-opus-5 단가로 매칭된다.
  "claude-opus-5-5": { input: 4.0, output: 20.0 },
  "claude-opus-5": { input: 5.0, output: 25.0 },
  "claude-opus-4-8": { input: 5.0, output: 25.0 },
  "claude-opus-4-7": { input: 5.0, output: 25.0 },
  "claude-opus-4-6-v1": { input: 5.0, output: 25.0 },
  "claude-opus-4-6": { input: 5.0, output: 25.0 },
  "claude-sonnet-5": { input: 2.0, output: 10.0 },
  "claude-sonnet-4-6": { input: 3.0, output: 15.0 },
  "claude-haiku-4-5-20251001-v1:0": { input: 1.0, output: 5.0 },
  "claude-haiku-4-5-20251001": { input: 1.0, output: 5.0 },
  // Amazon Nova
  "nova-2-lite-v1:0": { input: 0.06, output: 0.24 },
  // OpenAI GPT (Bedrock Mantle). cached-input 미추적 — input/output만.
  "gpt-5.4": { input: 2.75, output: 16.50 },
  "gpt-5.5": { input: 5.50, output: 33.00 },
  // GPT-5.6 세대 in-region/Geo 단가 — 2026-07-30 AWS 인하 반영 (Luna -80%, Terra -20%, Sol 불변).
  // 출처: AWS 공식 모델 카드 (Standard tier, short context ≤272K — 프로브는 항상 이 구간).
  // Sol: v2.28.1(2026-09-23) 프로모션 단가 — In-Region·Geo $4.40/$22, Global $4/$20 (최소 2026-11-21까지,
  // 종료 후 카드 재확인). backend/pricing.py와 동일하게 유지.
  "gpt-5.6-sol": { input: 4.40, output: 22.00 },
  "gpt-5.6-terra": { input: 2.20, output: 13.20 },
  "gpt-5.6-luna": { input: 0.22, output: 1.32 },
  // Global CRIS(openai:global:global.openai.*)는 in-region보다 저렴한 별도 단가 — "-global" suffix 키.
  // US CRIS(openai:us:us.openai.*, v2.25.0)도 같은 규칙으로 "-us" suffix 키를 쓴다.
  // ⚠️ 새 모델에 global/us pseudo-region을 추가하면 여기 "-global"/"-us" 키도 반드시 함께 추가할 것 —
  // 누락 시 getPricing의 prefix fallback이 in-region 단가로 조용히 매칭돼 과대 산정됨.
  "gpt-5.6-sol-global": { input: 4.00, output: 20.00 },
  "gpt-5.6-terra-global": { input: 2.00, output: 12.00 },
  "gpt-5.6-luna-global": { input: 0.20, output: 1.20 },
  // GPT 6 Astra — v2.27.0에서 AWS 공식 모델 카드 단가 반영 (Standard, ≤272K).
  // In-Region·Geo CRIS(US)는 OpenAI 정가 +10%, Global CRIS는 정가. 3키는 항상 함께 둔다 —
  // 하나만 있으면 prefix fallback이 나머지 채널을 그 단가로 오매칭한다.
  "gpt-6-astra": { input: 11.0, output: 55.0 },
  "gpt-6-astra-us": { input: 11.0, output: 55.0 },
  "gpt-6-astra-global": { input: 10.0, output: 50.0 },
  // GPT 6 Sol / Luna (v2.27.0 출시) — 출처: AWS Bedrock ListFoundationModelAgreementOffers
  // rate card (2026-09-23 조회; Sol offer-pycji3sz5gpcc, Luna offer-gmo53nkzc5or6).
  // input/output_tokens_standard = In-Region, Geo CRIS(US) / *_global_standard = Global CRIS.
  // 교차 검증: 같은 방식으로 조회한 Astra offer(offer-7epta7rbw5aws, standard 11/55, global 10/50)가
  // Astra 공식 모델 카드와 정확히 일치하고, 값은 OpenAI 정가(Sol $2/$10, Luna $0.10/$0.50)에
  // 문서화된 In-Region, Geo +10%를 더한 값과 같다. 모델 카드 미게시 → 게시되면 카드와 재대조 (ADR-028).
  // 3키는 항상 함께 둔다 — 하나만 있으면 prefix fallback이 나머지 채널을 그 단가로 오매칭한다.
  "gpt-6-sol": { input: 2.20, output: 11.00 },
  "gpt-6-sol-us": { input: 2.20, output: 11.00 },
  "gpt-6-sol-global": { input: 2.00, output: 10.00 },
  "gpt-6-luna": { input: 0.11, output: 0.55 },
  "gpt-6-luna-us": { input: 0.11, output: 0.55 },
  "gpt-6-luna-global": { input: 0.10, output: 0.50 },
};

/** model_id → ModelPricing. 매칭 실패 시 null. */
export function getPricing(modelId: string): ModelPricing | null {
  // anthropic:<id> → <id>
  let key = modelId.startsWith("anthropic:") ? modelId.slice("anthropic:".length) : modelId;
  // openai:<region>:<actual_id> → <actual_id>. pseudo-region "global"(Bedrock global CRIS)과
  // "us"(Bedrock US CRIS, v2.25.0)는 in-region과 단가가 달라 base 키에 "-global", "-us"
  // suffix를 붙여 구분한다. 실제 리전("us-east-1", "us-west-2" 등)은 suffix 없음.
  let openaiCris = ""; // "global" | "us" | ""
  if (key.startsWith("openai:")) {
    const segs = key.split(":");
    if (segs[1] === "global" || segs[1] === "us") openaiCris = segs[1];
    key = segs.slice(2).join(":");
  }
  // global.X.Y / us.X.Y → X.Y (Y는 그대로)
  const parts = key.split(".");
  if (parts.length >= 2 && (parts[0] === "global" || parts[0] === "us" || parts[0] === "eu" || parts[0] === "apac")) {
    parts.shift();
    key = parts.join(".");
  }
  // anthropic. / amazon. prefix 제거
  if (key.startsWith("anthropic.")) key = key.slice("anthropic.".length);
  if (key.startsWith("amazon.")) key = key.slice("amazon.".length);
  if (key.startsWith("openai.")) key = key.slice("openai.".length);
  if (openaiCris) key = `${key}-${openaiCris}`;

  // 정확 매칭 우선
  if (PRICE_TABLE[key]) return PRICE_TABLE[key];
  // 접미사 매칭 (e.g. claude-haiku-4-5-20251001 → claude-haiku-4-5-20251001-v1:0)
  for (const [k, v] of Object.entries(PRICE_TABLE)) {
    if (key.startsWith(k) || k.startsWith(key)) return v;
  }
  return null;
}

/** 입·출력 토큰 → USD. 단가 없으면 null. */
export function estimateCost(modelId: string, inputTokens: number, outputTokens: number): number | null {
  const p = getPricing(modelId);
  if (!p) return null;
  return (inputTokens * p.input + outputTokens * p.output) / 1_000_000;
}

export function formatCost(usd: number | null): string {
  if (usd === null || usd === undefined) return "—";
  if (usd < 0.001) return `$${(usd * 1000).toFixed(2)}m`; // milli-dollars
  if (usd < 1) return `$${(usd * 100).toFixed(2)}¢`;
  return `$${usd.toFixed(4)}`;
}
