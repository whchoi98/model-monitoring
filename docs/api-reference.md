# API Reference — Bedrock LLM Monitor

Base URL: `http://localhost:8000` (dev) | `https://d36s7ml54xwemr.cloudfront.net` (prod, CloudFront → internal ALB)

## Health (Public)

### GET /api/health
Liveness check (`backend/main.py`). Always returns `{"status": "ok"}`; it does not touch the database or Bedrock.

---

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

## Auto Probe (Public Reads, Authenticated Trigger)

### GET /api/auto-probe/status
Returns observed activity from database run reservations. This is not a live
query of the EventBridge Scheduler configuration. All returned timestamps
include a UTC offset.

**Response:**
```json
{
  "is_running": true,
  "current_cycle_running": false,
  "cycle_state": "completed",
  "last_run_id": 42,
  "last_run_status": "completed",
  "last_run_time": "2026-09-22T12:00:00Z",
  "last_completed_run_id": 42,
  "last_completed_time": "2026-09-22T12:02:00Z",
  "next_run_time": "2026-09-22T12:05:00Z",
  "interval_seconds": 300,
  "expected_model_count": 55,
  "category_count": 6,
  "category_interval_seconds": 1800,
  "channel_intervals": { "anthropic": 300 },
  "channel_category_intervals": { "anthropic": 1800 },
  "overdue_after_seconds": 600,
  "running_timeout_seconds": 900
}
```

`cycle_state` is `never_run`, `running`, `completed`, `failed`, or `overdue`.
`is_running` is true only for observed `running` / recent `completed` states;
it does not assert that the schedule is enabled. A reservation older than
15 minutes no longer counts as active. `last_completed_time` is the latest
visible result timestamp in the last completed run.

`channel_intervals` / `channel_category_intervals` (v2.29.0) give the collection
cadence per channel. Keys are the `model_id` prefix before the first `:` —
`anthropic` is Claude Platform on AWS (`anthropic:<id>`, labels
`Anthropic Claude … (US)`), whose cadence is `ANTHROPIC_CP_PROBE_INTERVAL_S`.
Since v2.29.1 the default is 300 s, so CP is probed every 5-minute cycle with the
cycle's workload like every other channel and the values equal the base fields
(`{"anthropic": 300}` / `{"anthropic": 1800}`, as above; the dashboard hides a
channel note whose value equals the base cadence). With
`ANTHROPIC_CP_PROBE_INTERVAL_S=600` (the v2.29.0 behavior) CP is probed every
other cycle with its own workload rotation and the fields read
`{"anthropic": 600}` / `{"anthropic": 3600}`. A model whose prefix is absent
uses the base fields. The value is the backend process's configuration (same
default as the AutoProber task); it is not read back from the Scheduler.

### GET /api/auto-probe/latest?category=code-gen
Returns each model's latest visible result from completed automatic runs
(v2.29.0: per model, not the rows of one run). The window is anchored at the
start of the most recent completed automatic run and sized by the model's own
cadence: 3 collection intervals without a category, and 2 workload rotations
with a category. At the default cadence that is 15 min and 60 min for every
channel, including Claude Platform on AWS (v2.29.1); with
`ANTHROPIC_CP_PROBE_INTERVAL_S=600` the CP windows widen to 30 min and 120 min. Rows of running
or failed runs are not published. The response keeps the `ProbeResultResponse`
array shape, sorted by `model_name`; rows can carry different `run_id` and
`category` values, so use `timestamp` for freshness. A catalog model absent
from the result is unmeasured, not a successful channel.

### GET /api/auto-probe/trend?hours=24
Returns automatic-run samples by result timestamp. `hours` is a positive number
up to 168; fractional windows are accepted. `category` is optional. Windows
over 24 hours use hourly averages and min–max values from successful calls;
failed-only buckets retain null metrics.

### GET /api/auto-probe/categories
Workload preset list from `auto_prober.WORKLOAD_PRESETS`, in rotation order — the valid values of the `category` filter above.

**Response:**
```json
[
  { "id": "chat-short", "label_ko": "짧은 대화", "label_en": "Short chat" },
  { "id": "reasoning", "label_ko": "추론", "label_en": "Reasoning" },
  { "id": "code-gen", "label_ko": "코드 생성", "label_en": "Code generation" },
  { "id": "summarize", "label_ko": "요약", "label_en": "Summarization" },
  { "id": "structured", "label_ko": "JSON 추출", "label_en": "JSON extraction" },
  { "id": "translate", "label_ko": "번역", "label_en": "Translation" }
]
```

### POST /api/auto-probe/trigger
**JWT required.** Reserves one automatic probe cycle before starting a
background worker. Manual triggers and scheduled cycles use the same
PostgreSQL transaction lock and active-reservation check.

- `202`: `{"triggered": true, "run_id": 43, "message": "..."}`
- `401`: missing/invalid credentials; no work is started.
- `409`: `{"detail":{"code":"cycle_running","run_id":43,"message":"..."}}`
- `503`: the reservation or worker could not be started.

An accepted automatic trigger is part of the automatic monitoring dataset.
It is separate from the user-configured SSE endpoint `/api/probes/run`.

### GET /api/auto-probe/anomalies?hours=12&category=code-gen
Probe-failure summary for the last N hours (1-168, default 12) — v2.12.0. Returns
`total_probes`, `total_failures`, and per-model `models` (failures, total, last_error,
last_at), sorted by failure count. Only automatic runs are included, including
available observations from a failed/ongoing run. The optional workload filter
matches the dashboard scope. Zero probes means no observations, not 100% success.

---

## Manual Probe (run = Auth Required)

### POST /api/probes/run
**Auth required.** SSE streaming probe execution.

**Request:**
```json
{
  "model_ids": ["us.anthropic.claude-opus-4-7"],
  "prompt": "Hello",
  "temperature": 0.1,
  "max_tokens": 256,
  "concurrency": 1,
  "repeat_count": 1
}
```

| Field | Default | Limits |
|-------|---------|--------|
| `model_ids` | (required) | every id must be in `GET /api/models`; unknown ids or an empty list → `400` |
| `prompt` | (required) | string |
| `temperature` | `0.1` | 0.0–1.0 |
| `max_tokens` | `256` | 1–4096 |
| `concurrency` | `1` | 1–20 |
| `repeat_count` | `1` | 1–50 |

Out-of-range values → `422`. Defaults and limits come from `ProbeRunRequest` in `backend/schemas.py`.

**Response:** Server-Sent Events stream (`start` with `run_id` / `ttft` / `token` / `result` / `error` / `complete`).
The run and its results are stored as a manual run (`is_auto = 0`).

### GET /api/probes/{run_id}
One stored probe run with all its results (`ProbeRunResponse`: `id`, `created_at`, `prompt`, `temperature`, `max_tokens`,
`concurrency`, `repeat_count`, `status`, `is_auto`, `results[]`). No auth. `404` if the run does not exist.

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

### GET /api/results?model_id=X&run_id=N&start_time=…&end_time=…&limit=100&offset=0
Query stored probe results (manual and automatic), newest first. All filters are optional: `model_id`, `run_id`,
`start_time` / `end_time` (ISO 8601, inclusive bounds on the result `timestamp`), `limit` (default 100, 1–1000), `offset`
(default 0). Rows whose label matches `HIDDEN_MODEL_PATTERNS` (default `(1P)`, the dormant 1P channels) are excluded.

### GET /api/results/latest
Latest results across all models.

### GET /api/results/stats
Statistics: avg, p50, p95, p99 per model, successful probes only. Optional `start_time`, `end_time`, `run_id`, `category`.
Without `start_time` and `run_id` the window is the last 24 hours.

---

## Prompt Sets (Auth Required for write)

### GET /api/prompts
List all prompt sets.

### POST /api/prompts
**Auth required.** Create a prompt set.

### DELETE /api/prompts/{id}
**Auth required.** Delete a prompt set.

### POST /api/prompts/optimize
**Auth required.** Bedrock Prompt Optimization (`bedrock-agent-runtime` `OptimizePrompt`, region `BEDROCK_OPTIMIZE_REGION`,
default `us-east-1`). Synchronous: the event stream is collected and returned as JSON.

**Request:**
```json
{ "prompt": "string (1-20000 chars)", "target_model_id": "global.anthropic.claude-opus-4-7" }
```

A `global.` / `us.` / `eu.` / `apac.` inference-profile prefix on `target_model_id` is stripped before the call (the API takes
foundation-model ids).

**Response (200):**
```json
{ "analyze_message": "string | null", "optimized_prompt": "string", "target_model_id": "as sent", "request_id": "string | null" }
```

`502` carries the Bedrock error code and message; `500` if no optimized prompt came back.

---

## Insights (regenerate = Auth Required)

### GET /api/insights/latest · GET /api/insights
Latest saved AI insight (bilingual Markdown) / list of recent insights.

### POST /api/insights/regenerate
**Auth required.** Non-streaming regenerate. Body `{"window": "6h"}` (default `6h`). Starts `insights_runner.run_once(window)`
in a backend thread and returns at once: `{"triggered": true, "message": "..."}`, or `{"triggered": false, ...}` while another
regeneration is running. Poll `GET /api/insights/latest` for the result.

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
30-day cost projection, per-channel comparison, cost trend. Since v2.30.0 (ADR-030) every successful probe row is priced at the
unit price in effect at its `timestamp`: `backend/price_history.py` joins `probe_results` to `price_history` on an exact
`model_id` match and the row's time range (`effective_from` up to the next price's `effective_from`, rows in status `seed` or
`verified`), and computes `row_cost = (input_tokens × input_per_mtok + output_tokens × output_per_mtok) / 1,000,000`. Summary and
channel-compare sum those row costs; a model without a price row has a null cost (shown as "-") while its tokens still count in
the totals, and channel-compare keeps adding a null as 0. Trend buckets use the same per-row costs. Before v2.30.0 costs were
computed at query time from `backend/pricing.py` (removed), so a price change re-priced every past row (ADR-025 rule, now
superseded). The time before the first PricingSync run is priced with the seed (`pricing_seed.py`, effective from
1970-01-01): price changes made before v2.30.0 are not reconstructed, and the 11 channels whose code price was wrong (Bedrock
Claude US, Nova 2.0 Lite) are corrected for all history. Response shapes are unchanged. The cache and long-context prices added
in v2.31.0 are display-only and never enter `row_cost`, and the `openai-list:<family_key>` channels have no probe rows.

### GET /api/reliability/multi-channel
Success rate + error buckets grouped by family/channel.

### GET /api/efficiency/score
0-100 weighted Token Efficiency Score per workload category. The cost component averages the per-row cost of successful rows
that have a price (the unit price in effect at each probe's time, v2.30.0).

### GET /api/analysis/stop-reasons · /api/analysis/output-length
Stop-reason distribution + output-length histograms.

---

## Unit Prices (Public) — v2.30.0, ADR-030 (cache, long-context and OpenAI official prices v2.31.0)

Data source for `/pricing` (Unit Prices / 비용 단가), Model Explorer card prices and Comparison Lab costs. Prices are USD per
1M tokens, Standard tier. Every cell has the input and output price and, since v2.31.0, the prompt-caching prices (cache read,
cache write, Claude 1-hour cache write) and, on GPT rows, the long-context prices; batch, flex and priority (fast) prices are not
included. Costs use input and output only: the cache and long-context prices and the OpenAI official price are display-only.
The PricingSync task (`python -m pricing_sync_runner --once`, every 12 hours) refreshes them from four official sources: the
Bedrock agreement-offer rate card (`ListFoundationModelAgreementOffers`, Bedrock Claude 20 + OpenAI 25 channels), the AWS Price
List API (`GetProducts`, Nova 2.0 Lite), Anthropic's `https://platform.claude.com/docs/en/about-claude/pricing.md` (Claude
Platform on AWS 9 channels) and OpenAI's `https://developers.openai.com/api/docs/pricing.md` (the OpenAI official price of the 8
active OpenAI families, stored as the display-only channels `openai-list:<family_key>`, v2.31.0). A change of more than 50% on
any price field (the boundary itself is applied) is stored as `pending_review` and waits for admin approval (see Admin below); a
field that was empty and is observed for the first time fills the current row in place (run result `enriched`, no new history
row). Observed prices are compared and stored at 6 decimals (a positive value that rounds to 0 counts as a parse failure; a
cache or long-context price may be exactly 0, as the Nova cache write is), and a parser error of any type only skips that
source's channels (`skipped:parse_failed`) without failing the run. Dormant 1P channels and labels matching
`HIDDEN_MODEL_PATTERNS` are excluded.

### GET /api/pricing
Current price table. The backend keeps a 60 s in-process cache per task (no `lang` in the key — the body carries both languages).

**Response (abridged):**
```json
{
  "currency": "USD",
  "unit": "per_1m_tokens",
  "generated_at": "2026-09-27T16:00:00Z",
  "last_sync": {"id": 14, "started_at": "2026-09-27T15:00:00Z", "finished_at": "2026-09-27T15:00:33Z", "status": "completed"},
  "pending_review": 0,
  "families": [
    {
      "family_key": "claude-opus-5-5", "family": "Claude Opus 5.5", "provider": "anthropic",
      "tiers": {
        "cp":          {"input": 4,   "output": 20, "cache_read": 0.2,  "cache_write": 5,   "cache_write_1h": 8,   "long": null, "model_ids": ["anthropic:claude-opus-5-5"], "source_ids": ["anthropic-pricing"], "footnotes": [1], "verification": "verified", "observed_at": "2026-09-27T15:00:00Z", "pending": null},
        "openai_list": null,
        "global":      {"input": 4,   "output": 20, "cache_read": 0.2,  "cache_write": 5,   "cache_write_1h": 8,   "long": null, "model_ids": ["global.anthropic.claude-opus-5-5"], "source_ids": ["offer:offer-7sp77cpl4rveu"], "footnotes": [2], "verification": "verified", "observed_at": "2026-09-27T15:00:00Z", "pending": null},
        "us":          {"input": 4.4, "output": 22, "cache_read": 0.22, "cache_write": 5.5, "cache_write_1h": 8.8, "long": null, "model_ids": ["us.anthropic.claude-opus-5-5"], "source_ids": ["offer:offer-7sp77cpl4rveu"], "footnotes": [2], "verification": "verified", "observed_at": "2026-09-27T15:00:00Z", "pending": null},
        "in_region": []
      },
      "notes": []
    },
    {
      "family_key": "gpt-6-astra", "family": "GPT 6 Astra", "provider": "openai",
      "tiers": {
        "cp": null,
        "openai_list": {"input": 10, "output": 50, "cache_read": 1,   "cache_write": 12.5,  "cache_write_1h": null, "long": {"input": 20, "output": 75,   "cache_read": 2,   "cache_write": 25},   "model_ids": ["openai-list:gpt-6-astra"], "source_ids": ["openai-pricing"], "footnotes": [3], "verification": "verified", "observed_at": "2026-09-27T15:00:00Z", "pending": null},
        "global":      {"input": 10, "output": 50, "cache_read": 1,   "cache_write": 12.5,  "cache_write_1h": null, "long": {"input": 20, "output": 75,   "cache_read": 2,   "cache_write": 25},   "model_ids": ["openai:global:global.openai.gpt-6-astra"], "source_ids": ["offer:offer-7epta7rbw5aws"], "footnotes": [4], "verification": "verified", "observed_at": "2026-09-27T15:00:00Z", "pending": null},
        "us":          {"input": 11, "output": 55, "cache_read": 1.1, "cache_write": 13.75, "cache_write_1h": null, "long": {"input": 22, "output": 82.5, "cache_read": 2.2, "cache_write": 27.5}, "model_ids": ["openai:us:us.openai.gpt-6-astra"], "source_ids": ["offer:offer-7epta7rbw5aws"], "footnotes": [4], "verification": "verified", "observed_at": "2026-09-27T15:00:00Z", "pending": null},
        "in_region": [
          {"regions": ["us-west-2"], "input": 11, "output": 55, "cache_read": 1.1, "cache_write": 13.75, "cache_write_1h": null, "long": {"input": 22, "output": 82.5, "cache_read": 2.2, "cache_write": 27.5}, "model_ids": ["openai:us-west-2:openai.gpt-6-astra"], "source_ids": ["offer:offer-7epta7rbw5aws"], "footnotes": [4], "verification": "verified", "observed_at": "2026-09-27T15:00:00Z", "pending": null}
        ]
      },
      "notes": []
    }
  ],
  "models": {
    "us.anthropic.claude-opus-5-5": {"input": 4.4, "output": 22, "verification": "verified"},
    "openai:global:global.openai.gpt-6-astra": {"input": 10, "output": 50, "verification": "verified"}
  },
  "references": [
    {"n": 1, "id": "anthropic-pricing", "kind": "anthropic_doc", "title_en": "Anthropic API pricing (Claude Platform on AWS uses standard pricing)", "title_ko": "Anthropic API 요금 (Claude Platform on AWS는 표준 요금)", "url": "https://platform.claude.com/docs/en/about-claude/pricing#model-pricing", "as_of": "2026-09-27"},
    {"n": 2, "id": "offer:offer-7sp77cpl4rveu", "kind": "agreement_offer", "title_en": "Amazon Bedrock agreement offer rate card, offer-7sp77cpl4rveu (Claude Opus 5.5)", "title_ko": "Amazon Bedrock 약정 오퍼 요금표, offer-7sp77cpl4rveu (Claude Opus 5.5)", "url": "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html", "as_of": "2026-09-27"},
    {"n": 3, "id": "openai-pricing", "kind": "openai_doc", "title_en": "OpenAI API pricing (Standard)", "title_ko": "OpenAI API 요금 (Standard)", "url": "https://developers.openai.com/api/docs/pricing", "as_of": "2026-09-27"},
    {"n": 4, "id": "offer:offer-7epta7rbw5aws", "kind": "agreement_offer", "title_en": "Amazon Bedrock agreement offer rate card, offer-7epta7rbw5aws (GPT 6 Astra)", "title_ko": "Amazon Bedrock 약정 오퍼 요금표, offer-7epta7rbw5aws (GPT 6 Astra)", "url": "https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModelAgreementOffers.html", "as_of": "2026-09-27"}
  ],
  "disclaimer": {"en": "This price list is compiled automatically from public sources for reference only and is not an official AWS statement. Always confirm final prices on the official pricing pages.", "ko": "이 가격표는 공개 자료를 자동으로 수집해 정리한 참고용 정보이며, AWS의 공식 입장이 아닙니다. 최종 가격은 반드시 공식 사이트에서 확인하세요."}
}
```

- `families` come in display order: provider Anthropic Claude → OpenAI → Amazon Nova (`pricing_sources.PROVIDER_ORDER`, v2.31.0;
  v2.30.0 put Amazon Nova second), then the family order of `frontend/src/lib/sortModels.ts` `FAMILY_ORDER`, mirrored and pinned
  by `pricing_sources.FAMILY_ORDER`. Clients render that order and the footnote numbers as sent; they never re-sort or renumber.
- `tiers` always has five keys in this order: `cp`, `openai_list`, `global`, `us` (an object or `null`) and `in_region` (always an
  array whose elements add `regions` and group the regions whose nine price values, verification and pending values are all
  equal, sorted by region name). `cp` is set only for Claude families and `openai_list` only for OpenAI families (v2.31.0).
- Every cell (single tier or `in_region` element) has `input`, `output`, `cache_read`, `cache_write`, `cache_write_1h` and `long`.
  `cache_read` is the cache hit (cached input) price; `cache_write` is the Claude 5-minute cache write, the OpenAI "cache writes"
  price or the Nova cache write; `cache_write_1h` is the Claude 1-hour cache write. Each is `null` when the source has no such
  price. `long` is `{input, output, cache_read, cache_write}` (the last two may be `null`) with the GPT long-context prices, which
  apply to requests above OpenAI's short-context limit (272K for GPT 5.4 and 5.5), when both long input and output are known,
  else `null` (always `null` for Claude and Nova). Cache and long-context prices are display-only.
- Prices are JSON numbers with at most 6 decimals and no trailing zeros (`4`, `4.4`, `0.11`, `0.0825`). A cache or long-context
  price can be `0` (the Nova cache write); input and output are always above 0.
- `verification` per cell: `verified` (observed by the latest finished run, whatever its status), `stale` (last observed
  earlier — `observed_at` tells when), `seed_only` (never observed by an official source yet). `pending` is the latest
  `pending_review` row of that `model_id` (`{id, input, output, cache_read, cache_write, cache_write_1h, long, observed_at}`) or
  `null`.
- `pending_review` counts every active channel (distinct `model_id`s) that has any `pending_review` row, whichever run left it;
  the admin list below shows every pending row. It is not the same number as `price_sync_runs.pending`, which counts only the
  channels that one run classified as pending (a new `pending_review` row or a re-observed held value, `no_baseline` included),
  so the run's number can be lower.
- `last_sync` is the latest finished run (any status) or `null` before the first run.
- `models` maps each active probe `model_id` to its current input and output price (used by Model Explorer and Comparison Lab).
  The display-only `openai_list` channels (`openai-list:<family_key>`) are not in it.
- `notes` holds price notes. Since v2.31.0 the GPT-5.6 Sol promotional price note (`kind` `promo`, `min_until` 2026-11-21,
  `prior_price` for `openai_list`, `global` and `in_region`) cites the OpenAI pricing page, which states that the promotion runs
  at least through November 21, 2026. Every note carries `source` (`openai_doc` or `manual_note`) and `source_id`, the reference
  its footnote points to (`openai-pricing` here, `note:<family_key>` for a manual note), numbered right after that family's
  cells when the source is official (a `manual_note` reference is numbered after the fixed official pages). A note
  disappears once a sync observes its `prior_price` on one of those tiers.
- `references[]`: `n` (1-based, in order of first citation, then fixed official pages, then the notes whose `source` is
  `manual_note`), `id` (`offer:<offerId>`, `pricelist:<usagetype>`, `anthropic-pricing`, `openai-pricing`, `official:<slug>`,
  `note:<family_key>`), `kind` (`agreement_offer`, `price_list`, `anthropic_doc`, `openai_doc`, `official_page`, `manual_note`),
  bilingual titles (`openai-pricing` is "OpenAI API pricing (Standard)" / "OpenAI API 요금 (Standard)"; a `manual_note` title
  names the family, e.g. "<family> promotion (manual note, <basis>)"), `url`, `as_of` (UTC date of the latest observation of that
  source, or the seed date 2026-09-27; `null` for `official_page` and `manual_note`, and a `manual_note` has `url: null`).
- Active channels are the backend's `AVAILABLE_MODELS` plus Claude Platform on AWS model ids observed in `price_history` in the
  last 30 days (so the table stays full when CP discovery failed at startup), minus hidden labels, plus one display-only
  `openai-list:<family_key>` channel per active OpenAI family (8, v2.31.0).

### GET /api/pricing/export?format=csv|md|json&lang=ko|en
Download the same table as a file: `Content-Disposition: attachment; filename="llm-monitor-unit-prices-YYYY-MM-DD.<csv|md|json>"`.
`lang` defaults to `ko`. `json` is the `/api/pricing` body. `md` starts with the disclaimer as a quote, then one table per
provider with that provider's own columns: Anthropic Claude `model | Claude Platform on AWS | AWS Bedrock - Global CRIS |
AWS Bedrock - US CRIS | AWS Bedrock - In Region`, OpenAI `model | OpenAI official price | AWS Bedrock - Global CRIS |
AWS Bedrock - US CRIS | AWS Bedrock - In Region` (KO "OpenAI 공식 가격"), Amazon Nova `model | AWS Bedrock - Global CRIS |
AWS Bedrock - US CRIS | AWS Bedrock - In Region` (no blank column). A cell is the price pair, regions and badges with `[^n]`
footnotes (a pending value lists only what changes, as the screen badge does: the pair when input or output changes, then the
changed cache prices and the long-context line, e.g. `4 / 20 (Pending review cache read 0.3)`; without the cache read the first
cache price names the cache, e.g. `4.4 / 22 (Pending review cache 1h write 17.6)`, KO `(검토 대기 캐시 1시간 쓰기 17.6)`), then `<br>` and the cache line (`cache read 0.2, write 5, 1h write 8`; KO `캐시 읽기 0.2, 쓰기 5, 1시간 쓰기 8`; only
the fields that are set) and, on GPT rows, `<br>` and the long-context line (`long context 20 / 75, cache read 2, write 25`; KO
`긴 컨텍스트 20 / 75, 캐시 읽기 2, 쓰기 25`); `in_region` elements are joined by `<br><br>`. Then come the notes, the references as
footnote definitions and the disclaimer again. `csv` is UTF-8 with a BOM, a first line that holds `# <disclaimer>` as one quoted
field (`"# <disclaimer>"`, so the commas in the text never split it into columns), the header
`provider,family,channel,regions,model_ids,input_usd_per_1m,output_usd_per_1m,cache_read_usd_per_1m,cache_write_usd_per_1m,cache_write_1h_usd_per_1m,long_input_usd_per_1m,long_output_usd_per_1m,long_cache_read_usd_per_1m,long_cache_write_usd_per_1m,verification,observed_at,footnotes,source_ids`,
one row per tier element in the order `cp`, `openai_list`, `global`, `us`, `in_region` (`channel` is that key; list columns are
space-separated; a price the source does not have is an empty field), a blank line, then
`reference_n,reference_id,kind,title,url,as_of` and the references.

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
`models` (5 representative models `fable-5-1`, `fable-5`, `opus-5-5`, `opus-5`, `sonnet-5` — Opus 5.5 since v2.28.0; this order is
also the UI order of model chips and per-cell model lists — with per-surface native ids; `mantle: null` plus `mantle_reason` when
Mantle does not serve the model) and `features` (39 rows = 33 documented "Build with Claude" features + 4 core
Messages checks + Models API + the strict_tool_use split; each with `label_ko/label_en`, `desc_ko/desc_en`, `doc_url`, per-surface
`documented` ∈ ga|beta|no|unknown, `verification` ∈ evidence|acceptance|negative|capability, `notes`). Since v2.24.0 the UI takes every
feature label and surface short name from this payload (`labelMaps`) — it is the single source for banners, modal titles and the drawer.

### GET /api/features/latest
Latest completed run: `run` (id, started_at, finished_at, `totals` — the 6 status counts plus `drift`; since v2.28.0 the status
counts sum to 975 cells = 813 probed + 162 pre-decided, catalog_version `2026-09-23`, running flag),
`previous_run_id`, `changes`, `drift`, `results`. `results[]` = one row per (feature, surface, model_key): `model_label`, `model_id`,
`status` ∈ supported|unsupported|broken|inconclusive|skipped|not_applicable, `documented`, `verdict` ∈ match|drift|undocumented|none,
`latency_ms` (null for runner pre-decided rows and for probes that failed before a measurement). `drift[]` = the results whose verdict is
`drift`. `changes[]` = cells whose status differs from the previous completed run:
`{feature, surface, model_key, model_label, before, after, kind}` — `before: null` for cells absent in the previous run;
**`kind` (v2.24.0)** is `"catalog"` when the cell did not exist before or when either side is a runner pre-decided row
(`latency_ms IS NULL AND error_message IS NULL` — a catalog rule such as `_NOT_APPLICABLE_BY_DOC`), else `"measured"`. A row with a NULL
`latency_ms` but an `error_message` is a failed probe (transport-init or executor failure), not a pre-decided row, so it counts as
`"measured"`. The first run after a representative-model addition (v2.28.0: `opus-5-5`) therefore lists every new cell (195) as
a `catalog` change. `Cache-Control: s-maxage=60`.
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
Start a manual Claude API Features run in a backend background thread (약 9분 since v2.28.0, 5 models — the duration the router
reports in `routers/features.py`; it was 약 7분 with 4 models). Rejects if already running. The daily scheduled run uses a separate Fargate task instead
(`python -m features_runner --once`).

---

## GPT on AWS bench (Public) — v2.18.0, 18 channels since v2.28.0

Data source for `/gpt-on-aws`. The GptBench task (`python -m gptbench_runner --once`, every 15 min) measures 18 channels —
Mantle in-region 11 + CRIS 7: GPT 5.4 (us-east-1, us-east-2, us-west-2), GPT 5.5 (us-east-1, us-east-2), GPT 5.6 Terra (Global,
us-east-1, us-east-2, us-west-2), GPT 6 Astra (Global, US, us-west-2), GPT 6 Sol and GPT 6 Luna (Global, US, us-east-1) — with a
fixed ~55.8k-token cached prompt, 1 unstored warm-up + 10 stored sequential calls per channel. Each call has a wall-clock cap
(`GPT_BENCH_CALL_TIMEOUT`, default 90 s — an expired call is stored as an error row `WallClockTimeout: …`), the client never retries
(`max_retries=0`), and the cycle skips trailing channels after `GPT_BENCH_DEADLINE` (780 s; Sol/Luna are last).

### GET /api/gptbench/latest
Latest **complete** cycle: `cycle_ts` + `channels[]` scorecards (`model_id`, `model_name`, `family`, `region`, `runs`, `success`,
`median_ttfb_ms`, `median_ttft_ms`, `median_gap_ms`, `p95_ttft_ms`, `cache_hit_rate`, `median_reasoning_tokens`, `last_error`).
A cycle counts as complete only 14 minutes after it started (deadline 13 min + margin); while the newest cycle is still running the
previous one is returned, so the payload lags the newest cycle by about 15–30 minutes. Sorted by family (GPT 6 Astra, Sol, Luna,
GPT 5.6 Terra, 5.5, 5.4; unknown families last) then region.

### GET /api/gptbench/trend?hours=24
Per-cycle median TTFB/TTFT/GAP and error count per channel (`series[].points[]`), `hours` 1–168 (default 24; 169+ → 422), complete cycles only.
The cap matches the UI's largest range (7 d) and is lowered from 720 in v2.28.0: this public endpoint aggregates in Python, and a 720 h
request at 18 channels loaded every row as an ORM object (~1 GB RSS, OOM risk on the 1 GiB backend task). It now reads only the seven
columns it aggregates (`model_id`, `model_name`, `cycle_ts`, `status`, `ttfb_ms`, `ttft_ms`, `gap_ms`) with the same response.

---

## Admin (Admin Only — `username == "admin"`)

### GET /api/admin/users · DELETE /api/admin/users/{username} · POST /api/admin/users/{username}/approve
User management.

### POST /api/admin/reset-monitoring-data
Purge stored probe data.

### GET /api/admin/pricing/pending — v2.30.0 (extra fields v2.31.0)
Unit prices waiting for review (`status = 'pending_review'`): for each row the current effective price, the new price, the change
ratios, the source and the reason — `changed` (a change above 50% on any price field) or `no_baseline` (a `model_id` with no
seed or verified price; approving it applies the price to all history, `effective_from` 1970-01-01). Response
`{"pending": [{id, model_id, family_key, channel, reason, current: {input, output, …} | null, new: {input, output, …}, change:
{input, output, …} | null, source_id, effective_from, observed_at}]}`, ordered by `id`, pending rows of every `model_id`. Since
v2.31.0 `current` and `new` also carry the optional `cache_read`, `cache_write`, `cache_write_1h`, `long_input`, `long_output`,
`long_cache_read` and `long_cache_write` (`null` when not set), and `change` has a ratio for every field set on both sides
(`input` and `output` are always there when a current price exists; an extra field whose current value is 0 has ratio `0` when
the new value is also 0, else `null`). `channel` can be `openai_list` (`model_id`
`openai-list:<family_key>`).

### POST /api/admin/pricing/pending/{row_id}/approve — v2.30.0
Sets the row to `verified` and keeps its `effective_from` (the start of the run that observed it, or 1970-01-01 for
`no_baseline`), so costs from that time use the new price. When a verified price of the same `model_id` already comes later in
the price lookup order `(effective_from, id)` (a later start, or the same start with a higher `id`), the response lists it in
`warnings`; that later price keeps winning from its own start.

### POST /api/admin/pricing/pending/{row_id}/reject — v2.30.0
Sets the row to `rejected`; the same value is not raised again until the official value changes.

Approve and reject both clear the `/api/pricing` cache of the backend task that served the request; other backend tasks can serve the previous
table for up to 60 s. A table that was being built while the cache was cleared is returned once but not cached (generation
counter). Both return `{ok, id, status, effective_from, warnings}`. `401` without a token, `403` for a non-admin user, `404` for
an unknown `row_id` (`detail` "단가 행 <id>을(를) 찾을 수 없습니다"), `409` when the row is not `pending_review` (`detail`
"단가 행 <id>는 검토 대기 상태가 아닙니다 (현재: <status>)").
