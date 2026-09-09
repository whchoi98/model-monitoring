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
  "model_count": 46
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
  { "id": "us.anthropic.claude-fable-5-1", "name": "Bedrock Claude Fable 5.1 (US)" },
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
in `MANTLE_ANTHROPIC_REGION`, chat_completions, responses). The in-code fallback is still `ap-northeast-1` when the env
is absent, but CDK injects `us-east-1` explicitly for the backend and every scheduler task (2026-09-05 decision —
`ap-northeast-1` serves only Opus 4.8 on `/anthropic`), so the deployed `messages_mantle` surface and the Claude API
Features Mantle column both probe `us-east-1`.

### GET /api/parity/latest
Latest completed run: `run` (id, started/finished, totals, running flag) + slim `results`
(model_id, model_name, surface, feature, status, latency_ms) + `previous_run_id` and
`changes` (cells whose status differs from the previous completed run; new cells have
`before: null`) — v2.12.0. `Cache-Control: s-maxage=60`.

### GET /api/parity/evidence?run_id=&model_id=&surface=&feature=
Full evidence for one matrix cell: evidence JSON (response snippet, tool call, usage, reason),
latency, error_message. 404 if the cell does not exist.

### POST /api/parity/trigger (Auth Required)
Start a manual parity run in a backend background thread (약 5-10분 — the duration the router itself reports in
`routers/parity.py`; the old "~3 min" was stale). Rejects if already running.
The 12-hour scheduled run uses a separate Fargate task instead (`python -m parity_runner --once`).

---

## Claude API Features (Public read, trigger = Auth Required) — v2.23.0, `changes[].kind` + failed-cell evidence v2.24.0

### GET /api/features/catalog
Feature catalog: `groups` (7 feature groups with `label_ko`/`label_en`), `surfaces` (5 — `cp`, `mantle`, `bedrock_messages`,
`bedrock_invoke`, `bedrock_converse`; each `{id, label, short, group, region}`, the Mantle region is `MANTLE_ANTHROPIC_REGION`),
`models` (4 representative models `fable-5-1`, `fable-5`, `opus-5`, `sonnet-5` with per-surface native ids; `mantle: null` plus
`mantle_reason` when Mantle does not serve the model) and `features` (39 rows = 33 documented "Build with Claude" features + 4 core
Messages checks + Models API + the strict_tool_use split; each with `label_ko/label_en`, `desc_ko/desc_en`, `doc_url`, per-surface
`documented` ∈ ga|beta|no|unknown, `verification` ∈ evidence|acceptance|negative|capability, `notes`). Since v2.24.0 the UI takes every
feature label and surface short name from this payload (`labelMaps`) — it is the single source for banners, modal titles and the drawer.

### GET /api/features/latest
Latest completed run: `run` (id, started_at, finished_at, `totals` — the 6 status counts plus `drift`, catalog_version, running flag),
`previous_run_id`, `changes`, `drift`, `results`. `results[]` = one row per (feature, surface, model_key): `model_label`, `model_id`,
`status` ∈ supported|unsupported|broken|inconclusive|skipped|not_applicable, `documented`, `verdict` ∈ match|drift|undocumented|none,
`latency_ms` (null for runner pre-decided rows and for probes that failed before a measurement). `drift[]` = the results whose verdict is
`drift`. `changes[]` = cells whose status differs from the previous completed run:
`{feature, surface, model_key, model_label, before, after, kind}` — `before: null` for cells absent in the previous run;
**`kind` (v2.24.0)** is `"catalog"` when the cell did not exist before or when either side is a runner pre-decided row
(`latency_ms IS NULL AND error_message IS NULL` — a catalog rule such as `_NOT_APPLICABLE_BY_DOC`), else `"measured"`. A row with a NULL
`latency_ms` but an `error_message` is a failed probe (transport-init or executor failure), not a pre-decided row, so it counts as
`"measured"`. `Cache-Control: s-maxage=60`.
With no completed run: `{"run": null, "previous_run_id": null, "changes": [], "drift": [], "results": [], "running": false}`.

### GET /api/features/evidence?run_id=&feature=&surface=&model_key=
Full evidence for one cell: the result row fields plus `evidence` JSON, `error_message`, and the catalog `doc_url`, `verification`,
`notes`. `evidence.request` is the request snapshot: `model`, the Anthropic/Converse body (strings over 200 chars trimmed, bytes as
`<N bytes>`), `anthropic_beta`, and the v2.24.0 meta keys `api` (e.g. `count_tokens`, `messages (stream)`, `GET /v1/models/{id}`,
`POST /v1/files → GET → DELETE`, or the boto operation `InvokeModel`/`Converse`/`CountTokens` on failed cells) and `note` for multi-call
probes (`same request twice; cache judged on 2nd call usage`, `2 calls: effort=low, then effort=ultra as negative control`, …).
Since v2.24.0 failed cells also carry the last body the transport actually sent (thread-local recorder; previously only `{"model"}`),
`error_message` keeps the boto operation name (`ValidationException (CountTokens): …`) and names the route for empty error bodies
(`HTTP 404: (empty body) GET /v1/files`), and the thinking probes store `usage`. 404 if the cell does not exist.

### POST /api/features/trigger (Auth Required)
Start a manual Claude API Features run in a backend background thread (약 7분 — the duration the router reports in
`routers/features.py`). Rejects if already running. The daily scheduled run uses a separate Fargate task instead
(`python -m features_runner --once`).

---

## Admin (Admin Only — `username == "admin"`)

### GET /api/admin/users · DELETE /api/admin/users/{username} · POST /api/admin/users/{username}/approve
User management.

### POST /api/admin/reset-monitoring-data
Purge stored probe data.
