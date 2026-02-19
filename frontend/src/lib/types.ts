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
  prompt_category?: string;
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
  current_prompt_category?: string;
  next_prompt_category?: string;
  total_prompt_categories?: number;
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
  prompt_category?: string;
}
