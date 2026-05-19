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
  endTime?: string
): Promise<ModelStats[]> {
  const searchParams = new URLSearchParams();
  if (startTime) searchParams.set("start_time", startTime);
  if (endTime) searchParams.set("end_time", endTime);

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

// --- Auto-probe API ---

export async function fetchAutoStatus(): Promise<AutoProbeStatus> {
  const res = await fetch(`${BASE}/api/auto-probe/status`);
  if (!res.ok) throw new Error(`Failed to fetch auto-probe status: ${res.statusText}`);
  return res.json();
}

export async function fetchAutoLatest(): Promise<ProbeResult[]> {
  const res = await fetch(`${BASE}/api/auto-probe/latest`);
  if (!res.ok) throw new Error(`Failed to fetch auto-probe latest: ${res.statusText}`);
  return res.json();
}

export async function fetchAutoTrend(hours: number = 24): Promise<TrendPoint[]> {
  const res = await fetch(`${BASE}/api/auto-probe/trend?hours=${hours}`);
  if (!res.ok) throw new Error(`Failed to fetch auto-probe trend: ${res.statusText}`);
  return res.json();
}

export async function triggerAutoProbe(): Promise<{ message: string; triggered: boolean }> {
  const res = await fetch(`${BASE}/api/auto-probe/trigger`, { method: "POST" });
  if (!res.ok) throw new Error(`Failed to trigger auto-probe: ${res.statusText}`);
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
