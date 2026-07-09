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
