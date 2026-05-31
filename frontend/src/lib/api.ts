import {
  ModelInfo,
  ProbeResult,
  ModelStats,
  PromptSet,
  ProbeConfig,
  AutoProbeStatus,
  TrendPoint,
  AuthUser,
  ChatStreamEvents,
  Insight,
} from "./types";

const BASE = "";

// --- Auth token management ---

let _token: string | null = null;

export function getToken(): string | null {
  if (_token) return _token;
  if (typeof window !== "undefined") {
    _token = localStorage.getItem("auth_token");
  }
  return _token;
}

export function setToken(token: string | null) {
  _token = token;
  if (typeof window !== "undefined") {
    if (token) localStorage.setItem("auth_token", token);
    else localStorage.removeItem("auth_token");
    // 다른 컴포넌트가 자체 useEffect로 mount 시 1회만 auth check 하는 패턴이라
    // 상단 헤더 로그인 후에도 InsightsPanel / FloatingChat가 옛 unauth state를 유지.
    // 전역 이벤트로 모든 listener가 재확인하도록 broadcast.
    window.dispatchEvent(new Event("auth-changed"));
  }
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

// --- Auth API ---

export async function login(username: string, password: string): Promise<{ access_token: string; username: string }> {
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "로그인 실패");
  }
  return res.json();
}

export async function register(username: string, password: string): Promise<AuthUser> {
  const res = await fetch(`${BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || "회원가입 실패");
  }
  return res.json();
}

export async function fetchMe(): Promise<AuthUser> {
  const res = await fetch(`${BASE}/api/auth/me`, { headers: authHeaders() });
  if (!res.ok) throw new Error("인증 만료");
  return res.json();
}

export async function fetchModels(): Promise<ModelInfo[]> {
  const res = await fetch(`${BASE}/api/models`);
  if (!res.ok) throw new Error(`Failed to fetch models: ${res.statusText}`);
  return res.json();
}

export async function fetchResults(params?: {
  model_id?: string;
  run_id?: number;
  limit?: number;
  offset?: number;
}): Promise<ProbeResult[]> {
  const searchParams = new URLSearchParams();
  if (params?.model_id) searchParams.set("model_id", params.model_id);
  if (params?.run_id) searchParams.set("run_id", String(params.run_id));
  if (params?.limit) searchParams.set("limit", String(params.limit));
  if (params?.offset) searchParams.set("offset", String(params.offset));

  const qs = searchParams.toString();
  const res = await fetch(`${BASE}/api/results${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`Failed to fetch results: ${res.statusText}`);
  return res.json();
}

export async function fetchStats(
  startTime?: string,
  endTime?: string,
  category?: string | null,
): Promise<ModelStats[]> {
  const searchParams = new URLSearchParams();
  if (startTime) searchParams.set("start_time", startTime);
  if (endTime) searchParams.set("end_time", endTime);
  if (category) searchParams.set("category", category);

  const qs = searchParams.toString();
  const res = await fetch(`${BASE}/api/results/stats${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`Failed to fetch stats: ${res.statusText}`);
  const data = await res.json();
  return data.models ?? [];
}

export async function fetchLatestResults(): Promise<ProbeResult[]> {
  const res = await fetch(`${BASE}/api/results/latest`);
  if (!res.ok)
    throw new Error(`Failed to fetch latest results: ${res.statusText}`);
  return res.json();
}

export async function fetchPromptSets(): Promise<PromptSet[]> {
  const res = await fetch(`${BASE}/api/prompts`);
  if (!res.ok)
    throw new Error(`Failed to fetch prompt sets: ${res.statusText}`);
  return res.json();
}

export async function createPromptSet(data: {
  name: string;
  prompts: string[];
  temperature: number;
  max_tokens: number;
}): Promise<PromptSet> {
  const res = await fetch(`${BASE}/api/prompts`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok)
    throw new Error(`Failed to create prompt set: ${res.statusText}`);
  return res.json();
}

export async function deletePromptSet(id: number): Promise<void> {
  const res = await fetch(`${BASE}/api/prompts/${id}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (!res.ok)
    throw new Error(`Failed to delete prompt set: ${res.statusText}`);
}

// Bedrock Simple Prompt Optimization.
export async function optimizePrompt(data: {
  prompt: string;
  target_model_id: string;
}): Promise<{
  analyze_message: string | null;
  optimized_prompt: string;
  target_model_id: string;
  request_id: string | null;
}> {
  const res = await fetch(`${BASE}/api/prompts/optimize`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`Failed to optimize prompt (${res.status}): ${text || res.statusText}`);
  }
  return res.json();
}

// --- Auto-probe API ---

export async function fetchAutoStatus(): Promise<AutoProbeStatus> {
  const res = await fetch(`${BASE}/api/auto-probe/status`);
  if (!res.ok) throw new Error(`Failed to fetch auto-probe status: ${res.statusText}`);
  return res.json();
}

export async function fetchAutoLatest(category?: string | null): Promise<ProbeResult[]> {
  const qs = category ? `?category=${encodeURIComponent(category)}` : "";
  const res = await fetch(`${BASE}/api/auto-probe/latest${qs}`);
  if (!res.ok) throw new Error(`Failed to fetch auto-probe latest: ${res.statusText}`);
  return res.json();
}

export async function fetchAutoTrend(hours: number = 24, category?: string | null): Promise<TrendPoint[]> {
  const sp = new URLSearchParams({ hours: String(hours) });
  if (category) sp.set("category", category);
  const res = await fetch(`${BASE}/api/auto-probe/trend?${sp.toString()}`);
  if (!res.ok) throw new Error(`Failed to fetch auto-probe trend: ${res.statusText}`);
  return res.json();
}

export async function triggerAutoProbe(): Promise<{ message: string; triggered: boolean }> {
  const res = await fetch(`${BASE}/api/auto-probe/trigger`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to trigger auto-probe: ${res.statusText}`);
  return res.json();
}

export async function fetchWorkloadCategories(): Promise<{ id: string; label_ko: string; label_en: string }[]> {
  const res = await fetch(`${BASE}/api/auto-probe/categories`);
  if (!res.ok) throw new Error(`Failed to fetch categories: ${res.statusText}`);
  return res.json();
}

export interface SSECallbacks {
  onToken?: (data: {
    model_id: string;
    model_name: string;
    iteration: number;
    token: string;
  }) => void;
  onTTFT?: (data: {
    model_id: string;
    model_name: string;
    iteration: number;
    ttft_ms: number;
  }) => void;
  onResult?: (data: ProbeResult) => void;
  onComplete?: (data: { run_id: number; total: number }) => void;
  onError?: (error: Error) => void;
}

export function runProbe(
  config: ProbeConfig,
  callbacks: SSECallbacks
): AbortController {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(`${BASE}/api/probes/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify(config),
        signal: controller.signal,
      });

      if (!res.ok) {
        throw new Error(`Probe request failed: ${res.statusText}`);
      }

      const reader = res.body?.getReader();
      if (!reader) {
        throw new Error("No response body reader available");
      }

      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split("\n\n");
        buffer = parts.pop() || "";

        for (const part of parts) {
          if (!part.trim()) continue;

          let eventType = "message";
          let eventData = "";

          const lines = part.split("\n");
          for (const line of lines) {
            if (line.startsWith("event:")) {
              eventType = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
              eventData = line.slice(5).trim();
            }
          }

          if (!eventData) continue;

          try {
            const parsed = JSON.parse(eventData);

            switch (eventType) {
              case "token":
                callbacks.onToken?.(parsed);
                break;
              case "ttft":
                callbacks.onTTFT?.(parsed);
                break;
              case "result":
                callbacks.onResult?.(parsed);
                break;
              case "complete":
                callbacks.onComplete?.(parsed);
                break;
            }
          } catch {
            // skip unparseable events
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      callbacks.onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  })();

  return controller;
}

// --- Chat (v2) ---

/** /api/chat/stream SSE — backend의 'delta', 'tool_call', 'final' 이벤트를 콜백으로 라우팅. */
export function chatStream(
  body: { message: string; session_id?: string | null },
  callbacks: ChatStreamEvents,
): AbortController {
  const controller = new AbortController();

  (async () => {
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(`${BASE}/api/chat/stream`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        throw new Error(`chat stream failed: ${res.status}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // SSE 이벤트는 빈 줄(\n\n)로 분리됨.
        let sep = buffer.indexOf("\n\n");
        while (sep !== -1) {
          const block = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          sep = buffer.indexOf("\n\n");

          let eventType = "message";
          let dataLine = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) eventType = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
          }
          if (!dataLine) continue;

          try {
            const parsed = JSON.parse(dataLine);
            switch (eventType) {
              case "delta":
                callbacks.onDelta?.(parsed.text ?? "");
                break;
              case "tool_call":
                callbacks.onToolCall?.(parsed);
                break;
              case "usage":
                callbacks.onUsage?.(parsed);
                break;
              case "warning":
                callbacks.onWarning?.(parsed.message ?? "");
                break;
              case "final":
                callbacks.onFinal?.(parsed);
                break;
              case "followups":
                if (Array.isArray(parsed.suggestions)) {
                  callbacks.onFollowups?.(parsed.suggestions.map((s: unknown) => String(s)));
                }
                break;
              case "error":
                callbacks.onError?.(new Error(parsed.message ?? "unknown"));
                break;
              default:
                // user / usage 등 무시
                break;
            }
          } catch {
            // skip unparseable events
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === "AbortError") return;
      callbacks.onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  })();

  return controller;
}

// --- Insights (v2) ---

export async function fetchLatestInsight(): Promise<Insight | null> {
  const res = await fetch(`${BASE}/api/insights/latest`);
  if (!res.ok) throw new Error(`fetchLatestInsight failed: ${res.statusText}`);
  return res.json();
}

export async function fetchInsights(limit: number = 10): Promise<Insight[]> {
  const res = await fetch(`${BASE}/api/insights?limit=${limit}`);
  if (!res.ok) throw new Error(`fetchInsights failed: ${res.statusText}`);
  return res.json();
}

export async function regenerateInsight(
  window: string = "6h",
): Promise<{ triggered: boolean; message: string }> {
  const res = await fetch(`${BASE}/api/insights/regenerate`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ window }),
  });
  if (!res.ok) throw new Error(`regenerateInsight failed: ${res.statusText}`);
  return res.json();
}

// --- Compare Lab (v2 Phase 1) ---

export interface CompareEvents {
  onStart?: (data: { total_tasks: number; model_ids: string[] }) => void;
  onTtft?: (data: { model_id: string; model_name: string; ttft_ms: number }) => void;
  onToken?: (data: { model_id: string; model_name: string; token: string }) => void;
  onResult?: (data: CompareResult) => void;
  onModelError?: (data: { model_id: string; model_name: string; error: string; total_latency_ms: number }) => void;
  onComplete?: (data: { total: number }) => void;
  onError?: (err: Error) => void;
}

export interface CompareResult {
  model_id: string;
  model_name: string;
  status: "success" | "error";
  ttft_ms: number | null;
  total_latency_ms: number;
  server_latency_ms: number | null;
  tps: number | null;
  input_tokens: number;
  output_tokens: number;
  output_text: string;
}

/** /api/compare/run SSE - N개 모델 동시 invoke. */
export function compareStream(
  body: { prompt: string; model_ids: string[]; max_tokens?: number; temperature?: number },
  callbacks: CompareEvents,
): AbortController {
  const controller = new AbortController();
  (async () => {
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      };
      const token = getToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(`${BASE}/api/compare/run`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const text = await res.text().catch(() => "");
        throw new Error(`compare stream failed: ${res.status} ${text}`);
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep = buffer.indexOf("\n\n");
        while (sep !== -1) {
          const block = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          sep = buffer.indexOf("\n\n");

          let eventType = "message";
          let dataLine = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) eventType = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
          }
          if (!dataLine) continue;

          try {
            const parsed = JSON.parse(dataLine);
            switch (eventType) {
              case "start": callbacks.onStart?.(parsed); break;
              case "ttft": callbacks.onTtft?.(parsed); break;
              case "token": callbacks.onToken?.(parsed); break;
              case "result": callbacks.onResult?.(parsed); break;
              case "error":
                if (parsed.model_id) callbacks.onModelError?.(parsed);
                else callbacks.onError?.(new Error(parsed.error ?? "unknown"));
                break;
              case "complete": callbacks.onComplete?.(parsed); break;
            }
          } catch {
            // parse 실패는 건너뜀
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      callbacks.onError?.(err as Error);
    }
  })();
  return controller;
}

// SSE 인사이트 재생성 - 토큰 단위 스트리밍.
export function streamRegenerateInsight(
  body: { window?: string; lang?: string },
  callbacks: {
    onDelta?: (text: string) => void;
    onFinal?: (payload: { ok: boolean; id?: number; error?: string }) => void;
    onError?: (err: Error) => void;
  },
): AbortController {
  const controller = new AbortController();
  (async () => {
    try {
      const headers: Record<string, string> = {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...authHeaders(),
      };
      const res = await fetch(`${BASE}/api/insights/stream-regenerate`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        const t = await res.text().catch(() => "");
        throw new Error(`insight stream failed: ${res.status} ${t}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep = buffer.indexOf("\n\n");
        while (sep !== -1) {
          const block = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          sep = buffer.indexOf("\n\n");
          let eventType = "message";
          let dataLine = "";
          for (const line of block.split("\n")) {
            if (line.startsWith("event:")) eventType = line.slice(6).trim();
            else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
          }
          if (!dataLine) continue;
          try {
            const parsed = JSON.parse(dataLine);
            if (eventType === "delta") callbacks.onDelta?.(parsed.text ?? "");
            else if (eventType === "final") callbacks.onFinal?.(parsed);
            else if (eventType === "error") callbacks.onError?.(new Error(parsed.message ?? "unknown"));
          } catch {
            // parse 실패는 건너뜀
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") return;
      callbacks.onError?.(err as Error);
    }
  })();
  return controller;
}

// --- Cost Dashboard (Phase 2) ---

export interface ModelCostRow {
  model_id: string;
  model_name: string;
  channel: string;
  samples: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number | null;
  avg_cost_per_call_usd: number | null;
}

export interface CostSummary {
  window: string;
  since: string;
  total_cost_usd: number;
  total_input_tokens: number;
  total_output_tokens: number;
  rows: ModelCostRow[];
}

export interface ChannelRow {
  channel: string;
  samples: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface ChannelCompare {
  window: string;
  since: string;
  channels: ChannelRow[];
}

export interface CostTrendPoint {
  bucket: string;
  model_name: string;
  cost_usd: number;
}

export interface CostTrend {
  window: string;
  since: string;
  bucket_minutes: number;
  points: CostTrendPoint[];
}

export async function fetchCostSummary(window: string = "24h"): Promise<CostSummary> {
  const res = await fetch(`${BASE}/api/cost/summary?window=${encodeURIComponent(window)}`);
  if (!res.ok) throw new Error(`fetchCostSummary failed: ${res.statusText}`);
  return res.json();
}

export async function fetchChannelCompare(window: string = "24h"): Promise<ChannelCompare> {
  const res = await fetch(`${BASE}/api/cost/channel-compare?window=${encodeURIComponent(window)}`);
  if (!res.ok) throw new Error(`fetchChannelCompare failed: ${res.statusText}`);
  return res.json();
}

export async function fetchCostTrend(window: string = "24h"): Promise<CostTrend> {
  const res = await fetch(`${BASE}/api/cost/trend?window=${encodeURIComponent(window)}`);
  if (!res.ok) throw new Error(`fetchCostTrend failed: ${res.statusText}`);
  return res.json();
}

// --- Multi-channel Reliability (Phase 4) ---

export interface ReliabilityChannelRow {
  channel: string;
  samples: number;
  success: number;
  error: number;
  overloaded: number;
  success_rate: number | null;
  avg_ttft_ms: number | null;
  p95_ttft_ms: number | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
  avg_tps: number | null;
  error_buckets: Record<string, number>;
}

export interface ReliabilityFamily {
  family: string;
  channels: ReliabilityChannelRow[];
}

export interface MultiChannelReliability {
  window: string;
  since: string;
  families: ReliabilityFamily[];
}

export async function fetchMultiChannelReliability(window: string = "24h"): Promise<MultiChannelReliability> {
  const res = await fetch(`${BASE}/api/reliability/multi-channel?window=${encodeURIComponent(window)}`);
  if (!res.ok) throw new Error(`fetchMultiChannelReliability failed: ${res.statusText}`);
  return res.json();
}

// --- Token Efficiency Score (Phase 5) ---

export interface ModelEfficiency {
  model_id: string;
  model_name: string;
  samples: number;
  success_rate: number | null;
  avg_output_tokens: number | null;
  avg_input_tokens: number | null;
  avg_cost_usd: number | null;
  avg_total_latency_ms: number | null;
  avg_tps: number | null;
  score: number | null;
  components: {
    cost: number | null;
    output_tokens: number | null;
    latency: number | null;
    tps: number | null;
    success_rate: number | null;
  };
}

export interface EfficiencyResponse {
  window: string;
  since: string;
  category: string | null;
  models: ModelEfficiency[];
}

export async function fetchEfficiency(window: string = "24h", category?: string | null): Promise<EfficiencyResponse> {
  const sp = new URLSearchParams({ window });
  if (category) sp.set("category", category);
  const res = await fetch(`${BASE}/api/efficiency/score?${sp.toString()}`);
  if (!res.ok) throw new Error(`fetchEfficiency failed: ${res.statusText}`);
  return res.json();
}

// --- Output Analysis: Stop Reasons + Output Length ---

export interface StopReasonRow {
  model_id: string;
  model_name: string;
  total: number;
  counts: Record<string, number>;
  percentages: Record<string, number>;
}

export interface StopReasonResponse {
  window: string;
  category: string | null;
  rows: StopReasonRow[];
}

export async function fetchStopReasons(window: string = "7d", category?: string | null): Promise<StopReasonResponse> {
  const sp = new URLSearchParams({ window });
  if (category) sp.set("category", category);
  const res = await fetch(`${BASE}/api/analysis/stop-reasons?${sp.toString()}`);
  if (!res.ok) throw new Error(`fetchStopReasons failed: ${res.statusText}`);
  return res.json();
}

export interface OutputLengthRow {
  model_id: string;
  model_name: string;
  n: number;
  mean: number;
  median: number;
  p50: number;
  p95: number;
  std: number;
  min: number;
  max: number;
  histogram: { bin: string; count: number }[];
}

export interface OutputLengthResponse {
  window: string;
  category: string | null;
  rows: OutputLengthRow[];
}

export async function fetchOutputLength(window: string = "7d", category?: string | null): Promise<OutputLengthResponse> {
  const sp = new URLSearchParams({ window });
  if (category) sp.set("category", category);
  const res = await fetch(`${BASE}/api/analysis/output-length?${sp.toString()}`);
  if (!res.ok) throw new Error(`fetchOutputLength failed: ${res.statusText}`);
  return res.json();
}
