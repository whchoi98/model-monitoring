// 모델별 토큰 단가 (USD per 1M tokens). Phase 2 Cost Dashboard에서도 재사용.
//
// 출처: AWS Bedrock public pricing + Anthropic API pricing.
// 가격이 변동되면 이 파일만 업데이트하면 됨.
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
  "claude-fable-5": { input: 10.0, output: 50.0 },
  "claude-opus-4-8": { input: 15.0, output: 75.0 },
  "claude-opus-4-7": { input: 15.0, output: 75.0 },
  "claude-opus-4-6-v1": { input: 15.0, output: 75.0 },
  "claude-opus-4-6": { input: 15.0, output: 75.0 },
  "claude-sonnet-5": { input: 2.0, output: 10.0 },
  "claude-sonnet-4-6": { input: 3.0, output: 15.0 },
  "claude-haiku-4-5-20251001-v1:0": { input: 1.0, output: 5.0 },
  "claude-haiku-4-5-20251001": { input: 1.0, output: 5.0 },
  // Amazon Nova
  "nova-2-lite-v1:0": { input: 0.06, output: 0.24 },
  // OpenAI GPT (Bedrock Mantle). cached-input 미추적 — input/output만.
  "gpt-5.4": { input: 2.75, output: 16.50 },
  "gpt-5.5": { input: 5.50, output: 33.00 },
  // GPT-5.6 세대는 Bedrock in-region 가격이 OpenAI 1P와 동일 (parity — 5.4/5.5식 10% 마크업 없음).
  "gpt-5.6-sol": { input: 5.00, output: 30.00 },
  "gpt-5.6-terra": { input: 2.50, output: 15.00 },
  "gpt-5.6-luna": { input: 1.00, output: 6.00 },
};

/** model_id → ModelPricing. 매칭 실패 시 null. */
export function getPricing(modelId: string): ModelPricing | null {
  // anthropic:<id> → <id>
  let key = modelId.startsWith("anthropic:") ? modelId.slice("anthropic:".length) : modelId;
  // openai:<region>:<actual_id> → <actual_id>
  if (key.startsWith("openai:")) key = key.split(":").slice(2).join(":");
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
