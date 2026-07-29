# API Reference — Bedrock LLM Monitor

Base URL: `http://localhost:8000` (dev) | `https://d36s7ml54xwemr.cloudfront.net` (prod, CloudFront → internal ALB)

## Authentication

### POST /api/auth/login
Login and receive JWT token. Only approved accounts can login.

**Request:**
```json
{ "username": "string", "password": "string" }
```

**Response (200):**
```json
{ "access_token": "string", "token_type": "bearer", "username": "string" }
```

### POST /api/auth/register
Register a new account (starts in pending approval state).

**Request:**
```json
{ "username": "email address (EmailStr enforced, v2.1.0)", "password": "string (4-100 chars)" }
```

**Response (201):**
```json
{ "id": 1, "username": "string", "approved": 0 }
```

### GET /api/auth/approve?token=TOKEN
One-click approval link (sent to admin via email). Returns HTML response.

### GET /api/auth/me
**Auth required.** Returns current user info.

---

## Auto Probe (Public)

### GET /api/auto-probe/status
Returns auto-prober state.

**Response:**
```json
{
  "is_running": true,
  "current_cycle_running": false,
  "last_run_time": "2026-04-16T16:48:53Z",
  "next_run_time": "2026-04-16T16:53:53Z",
  "interval_seconds": 300,
  "model_count": 42
}
```

### GET /api/auto-probe/latest
Returns the most recent probe result for each model.

### GET /api/auto-probe/trend?hours=24
Returns time-series data. Default: 24 hours. Supported: 1, 3, 6, 12, 24, 72, 168.

### POST /api/auto-probe/trigger
Trigger an immediate probe cycle.

### GET /api/auto-probe/anomalies?hours=12
Probe-failure summary for the last N hours (1-168, default 12) — v2.12.0. Returns
`total_probes`, `total_failures`, and per-model `models` (failures, total, last_error,
last_at), sorted by failure count. Powers the dashboard anomaly banner.

---

## Manual Probe (Auth Required)

### POST /api/probes/run
**Auth required.** SSE streaming probe execution.

**Request:**
```json
{
  "model_ids": ["us.anthropic.claude-opus-4-7"],
  "prompt": "Hello",
  "temperature": 0.7,
  "max_tokens": 256,
  "repeat_count": 1
}
```

**Response:** Server-Sent Events stream with progress and results.

---

## Models (Public)

### GET /api/models
Returns available model list.

**Response:**
```json
[
  { "id": "us.anthropic.claude-fable-5", "name": "Bedrock Claude Fable 5 (US)" },
  { "id": "us.anthropic.claude-opus-4-8", "name": "Bedrock Claude Opus 4.8 (US)" },
  { "id": "us.anthropic.claude-opus-4-7", "name": "Bedrock Claude Opus 4.7 (US)" }
]
```

---

## Results (Public)

### GET /api/results?model_id=X&limit=50&offset=0
Query stored probe results with optional filters.

### GET /api/results/latest
Latest results across all models.

### GET /api/results/stats
Statistics: avg, p50, p95, p99 per model.

---

## Prompt Sets (Auth Required for write)

### GET /api/prompts
List all prompt sets.

### POST /api/prompts
**Auth required.** Create a prompt set.

### DELETE /api/prompts/{id}
**Auth required.** Delete a prompt set.

---

## Insights (regenerate = Auth Required)

### GET /api/insights/latest · GET /api/insights
Latest saved AI insight (bilingual Markdown) / list of recent insights.

### POST /api/insights/stream-regenerate
**Auth required.** SSE stream — regenerate the insight summary.

---

## Chat (Auth Required)

### POST /api/chat/stream
**Auth required.** SSE stream — Claude Sonnet 4.6 chatbot with 4 Bedrock tools + per-turn dynamic followups.

---

## Comparison Lab (Auth Required)

### POST /api/compare/run
**Auth required.** SSE stream — invoke one prompt across N models in parallel
(`start` / `ttft` / `token` / `result` / `error` / `complete` events). No DB persistence.

---

## Analytics (Public)

### GET /api/cost/summary · /api/cost/channel-compare · /api/cost/trend
30-day cost projection, per-channel comparison, cost trend.

### GET /api/reliability/multi-channel
Success rate + error buckets grouped by family/channel.

### GET /api/efficiency/score
0-100 weighted Token Efficiency Score per workload category.

### GET /api/analysis/stop-reasons · /api/analysis/output-length
Stop-reason distribution + output-length histograms.

---

## Parity Run (Public read, trigger = Auth Required) — v2.11.0

### GET /api/parity/catalog
Feature catalog (19 features with bilingual labels/descriptions — label_ko/desc_ko + label_en/desc_en, v2.16.2) + 6 API surfaces
(converse, invoke_model, messages, messages_mantle — Bedrock Mantle `/anthropic`
in `MANTLE_ANTHROPIC_REGION` (default ap-northeast-1), chat_completions, responses).

### GET /api/parity/latest
Latest completed run: `run` (id, started/finished, totals, running flag) + slim `results`
(model_id, model_name, surface, feature, status, latency_ms) + `previous_run_id` and
`changes` (cells whose status differs from the previous completed run; new cells have
`before: null`) — v2.12.0. `Cache-Control: s-maxage=60`.

### GET /api/parity/evidence?run_id=&model_id=&surface=&feature=
Full evidence for one matrix cell: evidence JSON (response snippet, tool call, usage, reason),
latency, error_message. 404 if the cell does not exist.

### POST /api/parity/trigger (Auth Required)
Start a manual parity run in a backend background thread (~3 min). Rejects if already running.
The 12-hour scheduled run uses a separate Fargate task instead (`python -m parity_runner --once`).

---

## Admin (Admin Only — `username == "admin"`)

### GET /api/admin/users · DELETE /api/admin/users/{username} · POST /api/admin/users/{username}/approve
User management.

### POST /api/admin/reset-monitoring-data
Purge stored probe data.
