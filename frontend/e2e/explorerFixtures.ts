import type { ExplorerChange, ExplorerExample, ExplorerLatest, ExplorerResult, ModelInfo } from "../src/lib/types";

// ── GET /api/explorer/latest (v2.40.0) ─────────────────────────────────────
// The real examples come from backend/model_explorer/examples.py (pinned by backend/tests/test_explorer_examples.py).
// This fixture only needs the shape the page reads: per channel type the same API tabs, and code that names the call
// region and the invoke model id, so the specs can check what the modal shows.

function nativeId(id: string): string {
  if (id.startsWith("anthropic:")) return id.slice("anthropic:".length);
  if (id.startsWith("openai:") || id.startsWith("bedrock:")) return id.split(":").slice(2).join(":");
  return id;
}

function example(api_id: ExplorerExample["api_id"], api: string, label: string, code: string): ExplorerExample {
  return {
    api_id, api, label, language: "python",
    description: { ko: `${api} 설명`, en: `${api} description` },
    code: { ko: `# 예제\n${code}`, en: `# Example\n${code}` },
    code_sha: `sha-${api_id}`,
    result: null,
  };
}

export function explorerExamples(id: string): ExplorerExample[] {
  const mid = nativeId(id);
  if (id.startsWith("anthropic:")) {
    return [example("messages", "Messages API", "Python (anthropic SDK)", `with client.messages.stream(model="${mid}") as stream:`)];
  }
  if (id.startsWith("openai:")) {
    return [example("responses", "Responses API", "Python (openai SDK)", `stream = client.responses.create(model="${mid}")`)];
  }
  const region = id.startsWith("bedrock:") ? id.split(":")[1] : id.startsWith("us") ? "us-east-1" : "ap-northeast-2";
  const converse = example("converse", "Converse API", "Python (boto3)",
    `client = boto3.client("bedrock-runtime", region_name="${region}")\nresponse = client.converse_stream(modelId="${mid}")`);
  if (!id.includes("anthropic")) return [converse];
  return [
    converse,
    example("invoke_model", "InvokeModel API", "Python (boto3)", `response = client.invoke_model(modelId="${mid}")`),
    example("messages", "Messages API", "Python (anthropic SDK)", `client = AnthropicBedrock(aws_region="${region}")`),
  ];
}

export function explorerResult(status: ExplorerResult["status"], overrides: Partial<ExplorerResult> = {}): ExplorerResult {
  return {
    status,
    latency_ms: 1180,
    attempts: status === "failed" ? 2 : 1,
    error_message: status === "failed" ? "KeyError: 'text'\nTraceback (most recent call last):\n  File \"example.py\", line 15"
      : status === "skipped" ? "자격 증명 미주입: OPENAI_1P_API_KEY" : null,
    output_excerpt: status === "passed" ? "Hello! How can I help you today?" : null,
    run_id: 12,
    verified_at: "2026-11-05T18:02:00Z",
    stale_code: false,
    ...overrides,
  };
}

/** A latest payload for these cards; `results` sets a result per "model id|api id". */
export function explorerLatest(models: ModelInfo[], options: {
  results?: Record<string, ExplorerResult>;
  changes?: ExplorerChange[];
  previousRunId?: number | null;
  run?: ExplorerLatest["run"];
  running?: boolean;
} = {}): ExplorerLatest {
  const results = options.results ?? {};
  const run = options.run === undefined
    ? { id: 12, started_at: "2026-11-05T18:00:00Z", finished_at: "2026-11-05T18:02:00Z", totals: { passed: 83, failed: 1, skipped: 1 } }
    : options.run;
  return {
    run,
    running: options.running ?? false,
    previous_run_id: options.previousRunId === undefined ? (run ? 11 : null) : options.previousRunId,
    changes: options.changes ?? [],
    models: Object.fromEntries(models.map((model) => [model.id, {
      examples: explorerExamples(model.id).map((ex) => ({ ...ex, result: results[`${model.id}|${ex.api_id}`] ?? null })),
    }])),
  };
}
