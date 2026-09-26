export interface ModelInfo {
  id: string;
  name: string;
}

export interface ProbeResult {
  id?: number;
  run_id?: number;
  model_id: string;
  model_name: string;
  timestamp?: string;
  prompt?: string;
  status: string;
  ttft_ms: number | null;
  total_latency_ms: number | null;
  server_latency_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  tps: number | null;
  output_text?: string;
  error_message?: string;
  iteration: number;
  category?: string | null;
}

export interface WorkloadCategory {
  id: string;
  label_ko: string;
  label_en: string;
}

export interface ModelStats {
  model_name: string;
  model_id: string;
  count: number;
  avg_ttft_ms: number | null;
  p50_ttft_ms: number | null;
  p95_ttft_ms: number | null;
  p99_ttft_ms: number | null;
  avg_latency_ms: number | null;
  p50_latency_ms: number | null;
  p95_latency_ms: number | null;
  p99_latency_ms: number | null;
  avg_tps: number | null;
  p50_tps: number | null;
  p95_tps: number | null;
  p99_tps: number | null;
  avg_server_latency_ms: number | null;
  p50_server_latency_ms: number | null;
  p95_server_latency_ms: number | null;
  p99_server_latency_ms: number | null;
}

export interface StreamToken {
  model_id: string;
  model_name: string;
  iteration: number;
  token: string;
}

export interface PromptSet {
  id: number;
  name: string;
  prompts: string[];
  temperature: number;
  max_tokens: number;
}

export interface ProbeConfig {
  model_ids: string[];
  prompt: string;
  temperature: number;
  max_tokens: number;
  concurrency: number;
  repeat_count: number;
}

export interface AutoProbeStatus {
  is_running: boolean;
  last_run_time: string | null;
  next_run_time: string | null;
  interval_seconds: number;
  current_cycle_running: boolean;
  last_completed_time?: string | null;
  category_interval_seconds?: number;
  /** v2.29.0 — per-channel cadence keyed by the model_id prefix before the first ":" ("anthropic" = Claude
   *  Platform on AWS: 300 by default since v2.29.1, 600 with the backend knob raised). Absent channels use
   *  interval_seconds. */
  channel_intervals?: Record<string, number>;
  /** v2.29.0 — the same per workload category (category_interval_seconds counterpart, "anthropic" 1800 by
   *  default, 3600 at 600 s). */
  channel_category_intervals?: Record<string, number>;
  expected_model_count?: number;
  cycle_state?: "running" | "waiting" | "completed" | "overdue" | "failed" | "unknown" | "never_run";
  overdue_after_seconds?: number;
  running_timeout_seconds?: number;
}

export interface AutoProbeAnomalies {
  hours: number;
  category?: string | null;
  total_probes: number;
  total_failures: number;
  models: { model_name: string; failures: number; total: number; last_error: string | null }[];
}

export interface AuthUser {
  id: number;
  username: string;
}

export interface TrendPoint {
  model_id: string;
  model_name: string;
  timestamp: string;
  ttft_ms: number | null;
  total_latency_ms: number | null;
  tps: number | null;
  status: string;
  category?: string | null;
  // 집계 구간(hours>24)의 min–max 밴드 — 원본(5분 해상도) 행은 null (v2.7.1)
  ttft_ms_min?: number | null;
  ttft_ms_max?: number | null;
  total_latency_ms_min?: number | null;
  total_latency_ms_max?: number | null;
  tps_min?: number | null;
  tps_max?: number | null;
}

// ---------------------------------------------------------------------------
// Chat + Insights (v2)
// ---------------------------------------------------------------------------

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  text: string;
  /** assistant 메시지 도중 발생한 tool 호출 (UI badge 용도). */
  toolCalls?: { name: string; input: unknown }[];
}

export interface ChatStreamEvents {
  onDelta?: (text: string) => void;
  onToolCall?: (call: { name: string; input: unknown; toolUseId: string }) => void;
  onUsage?: (usage: Record<string, unknown>) => void;
  onWarning?: (message: string) => void;
  /** 정상/예외 모두에서 정확히 1회 호출됨 (backend의 final 이벤트). */
  onFinal?: (payload: { ok: boolean; error?: string; session_id?: string }) => void;
  /** 대화 맥락 기반 동적 follow-up 3개 (응답 종료 직전 emit). */
  onFollowups?: (suggestions: string[]) => void;
  onError?: (err: Error) => void;
}

export interface Insight {
  id: number;
  window_start: string;
  window_end: string;
  summary_md: string;
  summary_md_en?: string | null;
  model_breakdown: Record<string, unknown> | null;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Unit prices (v2.30.0) — GET /api/pricing. The backend owns ordering and footnote numbers.
// ---------------------------------------------------------------------------

export type PriceVerification = "verified" | "stale" | "seed_only" | "none";

export interface PricingPending {
  id: number;
  input: number;
  output: number;
  observed_at: string;
}

export interface PricingTier {
  input: number;
  output: number;
  model_ids: string[];
  source_ids: string[];
  footnotes: number[];
  verification: PriceVerification;
  observed_at: string | null;
  pending: PricingPending | null;
}

export interface PricingInRegionTier extends PricingTier {
  regions: string[];
}

export interface PricingNote {
  family_key: string;
  kind: "promo";
  min_until: string;
  prior_price: Record<string, { input: number; output: number }>;
  text_ko: string;
  text_en: string;
  source: "manual_note";
}

export interface PricingFamily {
  family_key: string;
  family: string;
  provider: "anthropic" | "amazon" | "openai";
  tiers: {
    cp: PricingTier | null;
    global: PricingTier | null;
    us: PricingTier | null;
    in_region: PricingInRegionTier[];
  };
  notes: PricingNote[];
}

export interface PricingReference {
  n: number;
  id: string;
  kind: "agreement_offer" | "price_list" | "anthropic_doc" | "official_page" | "manual_note";
  title_en: string;
  title_ko: string;
  url: string | null;
  as_of: string | null;
}

export interface PricingModelPrice {
  input: number;
  output: number;
  verification: PriceVerification;
}

export interface PricingResponse {
  currency: "USD";
  unit: "per_1m_tokens";
  generated_at: string;
  last_sync: { id: number; started_at: string; finished_at: string | null; status: string } | null;
  pending_review: number;
  families: PricingFamily[];
  models: Record<string, PricingModelPrice>;
  references: PricingReference[];
  disclaimer: { en: string; ko: string };
}
