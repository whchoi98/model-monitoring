# Design — Add OpenAI GPT 5.4 / 5.5 monitoring (v2.4.0)

**Date:** 2026-06-26
**Status:** Proposed (awaiting user review)
**Author:** WooHyung Choi (with Claude Code)

## 1. Goal / 목표

Add OpenAI **GPT-5.4** and **GPT-5.5** to the Bedrock LLM Monitor as a **third provider call-path** (alongside boto3-Bedrock and Anthropic-CP). The models are served through the **Bedrock Mantle OpenAI-compatible endpoint** (`/openai/v1`, OpenAI Chat Completions shape, Bedrock long-term API key as bearer token).

## 2. Locked decisions / 확정 결정

| Decision | Choice |
|---|---|
| Channels | **4** — each model in **both** us-east-1 and us-east-2 (catalog 18 → **22**) |
| Family / label prefix | New **`OpenAI`** family. Labels: `OpenAI GPT 5.4 (us-east-1)` etc. Channel suffix = raw region. |
| `cost._channel()` bucket | `"OpenAI"` |
| Pricing | input/output only (cached-input **not** tracked — consistent with existing entries) |
| Version | `v2.3.0` → `v2.4.0` |

### Catalog (4 channels)

| internal model_id key | model_name label | base_url env |
|---|---|---|
| `openai:us-east-1:openai.gpt-5.4` | `OpenAI GPT 5.4 (us-east-1)` | `OPENAI_US_EAST_1_BASE_URL` |
| `openai:us-east-2:openai.gpt-5.4` | `OpenAI GPT 5.4 (us-east-2)` | `OPENAI_US_EAST_2_BASE_URL` |
| `openai:us-east-1:openai.gpt-5.5` | `OpenAI GPT 5.5 (us-east-1)` | `OPENAI_US_EAST_1_BASE_URL` |
| `openai:us-east-2:openai.gpt-5.5` | `OpenAI GPT 5.5 (us-east-2)` | `OPENAI_US_EAST_2_BASE_URL` |

Key scheme `openai:<region>:<actual_model_id>` mirrors the existing `anthropic:` namespace. Region encodes the channel (a single `model_id` is probed in two regions, so the region — not a `global./us.` prefix — is the channel discriminator). `actual_model_id` (`openai.gpt-5.4`) is what gets sent as the OpenAI `model` field.

## 3. Architecture — the third provider path

`prober.py` infers provider from the model_id key prefix:
- `anthropic:` → Anthropic SDK (CP-on-AWS)
- `openai:` → **NEW** OpenAI SDK (Bedrock Mantle)
- otherwise → boto3 `converse_stream` (Bedrock)

The OpenAI path is closest to the Anthropic path: a custom-`base_url` SDK client with bearer auth and native streaming for TTFT capture. The boto3 `client` arg passed by callers is ignored on the OpenAI branch (as it is on the Anthropic branch).

## 4. Backend changes

### 4.1 `backend/prober.py`
- **Helpers** (near existing `_is_anthropic_direct`, ~line 133):
  - `_is_openai_direct(model_id) -> model_id.startswith("openai:")`
  - `_openai_parts(model_id) -> (region, actual_id)` via `model_id.split(":", 2)[1:]`
  - `_openai_base_url(region)` → reads `OPENAI_US_EAST_1_BASE_URL` / `OPENAI_US_EAST_2_BASE_URL`
  - `_get_openai_client(base_url)` → cached `OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=base_url)` (cache keyed by base_url, mirroring `_client_cache`)
  - `_register_openai_models()` → if `OPENAI_API_KEY` and the base-url envs are set, register the 4 `AVAILABLE_MODELS` entries. Called at the same sites as `_discover_anthropic_models()` (main.py lifespan + auto_prober_runner — confirm during impl).
- **Dispatch branch** in `_probe_single_model` (~line 227) and `_compare_single_model` (~line 625): add `elif _is_openai_direct(model_id):`.
- **OpenAI branch behavior:**
  - `region, actual_id = _openai_parts(model_id)`; `client = _get_openai_client(_openai_base_url(region))`
  - `stream = client.chat.completions.create(model=actual_id, messages=[{"role":"user","content":prompt}], stream=True, stream_options={"include_usage": True}, max_tokens=max_tokens)` — **temperature omitted** (gpt-5 reasoning rejects non-default temperature; same as Anthropic branch)
  - For each chunk: `delta = chunk.choices[0].delta.content`; on first non-empty → set `first_token_time`, emit `ttft` SSE; emit `token` SSE per delta (mirror lines 237-253)
  - `finish_reason` from `chunk.choices[0].finish_reason` when present, mapped: `stop→end_turn`, `length→max_tokens`, `tool_calls→tool_use`, `content_filter→content_filtered`
  - usage from the final chunk's `chunk.usage`: `prompt_tokens→input_tokens`, `completion_tokens→output_tokens`
  - `server_latency_ms = None`; total_latency_ms / TPS computed by the shared success block (no change)
- **Retry classification**: add OpenAI overload/throttle markers to `_RETRYABLE_PATTERNS` (~line 166): `"rate_limit"`, `"RateLimitError"`, `"ServiceUnavailable"`, `"overloaded"`.

### 4.2 `backend/requirements.txt`
- Add `openai>=1.0.0` (not currently a dependency).

### 4.3 `backend/pricing.py`
- Extend `_normalize_key`: strip `openai:<region>:` prefix (`key.split(":", 2)[-1]` when `key.startswith("openai:")`) then strip a leading `openai.` vendor segment → base key.
- Add to `PRICE_TABLE`:
  - `"gpt-5.4": {"input": 2.75, "output": 16.50}`
  - `"gpt-5.5": {"input": 5.50, "output": 33.00}`
- Keys `gpt-5.4` / `gpt-5.5` are mutually non-prefixing and don't collide with `claude-*`/`nova-*` (bidirectional-startswith fallback is safe). Do **not** add a bare `gpt-5` key.

### 4.4 `backend/routers/cost.py`
- `_channel()`: add `if model_id.startswith("openai:"): return "OpenAI"` (before the `"Other"` fallback) so channel-compare / summary dashboards label OpenAI correctly.

## 5. Frontend changes (mirrors `lib/pricing.ts` + 4 display files)

### 5.1 `frontend/src/lib/pricing.ts`
- Mirror the `_normalize_key` `openai:`/`openai.` strip logic in `getPricing`, and add the same 2 `PRICE_TABLE` entries (byte-identical to backend).

### 5.2 `frontend/src/lib/sortModels.ts`
- `FAMILY_ORDER`: append `'GPT 5.5'`, `'GPT 5.4'` (after `'Nova 2.0 Lite'`).
- `channelRank`: add `if (name.startsWith('OpenAI ')) return 3;` (own tier; within-family the two regions sort stably us-east-1 → us-east-2).
- `isExcludedModel` unchanged (blacklist; OpenAI passes through).

### 5.3 `frontend/src/components/TrendChart.tsx`
- `MODEL_COLORS`: 4 exact-label keys (greens, distinct from Nova lime / Claude palette):
  - `'OpenAI GPT 5.5 (us-east-1)': '#10a37f'`
  - `'OpenAI GPT 5.5 (us-east-2)': '#0d8a6a'`
  - `'OpenAI GPT 5.4 (us-east-1)': '#34d399'`
  - `'OpenAI GPT 5.4 (us-east-2)': '#059669'`
- `FAMILY_FALLBACK`: `['GPT 5.5', '#10a37f']`, `['GPT 5.4', '#34d399']`.

### 5.4 `frontend/src/components/StreamingView.tsx` (Comparison Lab / manual probe)
- `extractModelName`: add branches before the `return modelId` fallback — `gpt-5-5`/`gpt-5.5` → `GPT 5.5 (<region>)`, `gpt-5-4`/`gpt-5.4` → `GPT 5.4 (<region>)` (parse region from the `openai:<region>:` prefix; do NOT apply the Bedrock `global/us` split).
- `MODEL_COLORS`: Tailwind `bg-*` entries for the returned names (e.g. greens).

### 5.5 `frontend/src/lib/version.ts`
- `APP_VERSION = 'v2.4.0'`.

### 5.6 No change
- `AutoDashboard.tsx` (blacklist filter passes OpenAI through), `PromptsPanel.tsx` (OptimizePrompt is Bedrock-only), `ModelStatusGrid.tsx` (inherits sortModels).

## 6. CDK changes

### 6.1 `cdk/lib/stacks/app-services-stack.ts` (backend task)
- After the anthropic SSM imports: `const openaiApiKeyParam = ssm.StringParameter.fromSecureStringParameterAttributes(this, 'OpenAiApiKeyParam', { parameterName: '/bedrock-monitor/openai-api-key' });`
- `backendSecrets`: `OPENAI_API_KEY: ecs.Secret.fromSsmParameter(openaiApiKeyParam)`
- `backendEnv`: 4 plain vars — `OPENAI_US_EAST_1_BASE_URL`, `OPENAI_US_EAST_2_BASE_URL`, `BEDROCK_OPENAI_GPT_54_MODEL_ID`, `BEDROCK_OPENAI_GPT_55_MODEL_ID`.

### 6.2 `cdk/lib/stacks/scheduler-stack.ts` (autoprober + insights)
- Same SSM import + same `secrets`/`environment` additions inside `buildTaskDef` (single edit reaches both autoProber and insights tasks). Keep env values identical to app-services-stack to avoid drift.

### 6.3 IAM
- **No change.** Bearer-token (Bedrock API key) auth does not consult the task role's IAM identity. (If a path ever falls back to SigV4 `bedrock-runtime` for `openai.*`, the existing `foundation-model/*` wildcard already matches — but the base-URL design uses bearer auth.)

### 6.4 Operator prerequisite (deploy runbook)
- Pre-create the SSM SecureString once per region before deploy:
  `aws ssm put-parameter --region ap-northeast-2 --name /bedrock-monitor/openai-api-key --type SecureString --value '<bedrock-long-term-api-key>'`
- Add to `docs/runbooks/deploy.md` alongside the existing anthropic-api-key / jwt-secret-key steps.
- **Security:** the API key shared in chat must be **rotated** after wiring (it is in conversation history).

## 7. Docs

- `CLAUDE.md`: 18 → 22 at all count mentions; line 90 → `22개 (13 Bedrock + 5 Anthropic CP + 4 OpenAI)`; Monitored Models section header → 22; add an OpenAI sub-section/rows; extend label-policy note for the `OpenAI` prefix.
- `README.md`: 18 → 22 (EN + KO); extend the 3-path channel description to mention the Bedrock-Mantle OpenAI path; ADR range → ADR-019.
- `docs/architecture.md`: topology diagram counts 18 → 22; ADR range + new table row.
- `docs/api-reference.md`: `model_count` 18 → 22.
- `frontend/src/components/CLAUDE.md`: line 8 `(15 models)` → `(22 models)` (fixes pre-existing stale count).
- `docs/decisions/ADR-019-openai-bedrock-mantle-provider-path.md`: **new** — provider path, model-id format, region availability, pricing, label convention, catalog 18 → 22.
- Update memory `adding-a-monitored-model.md` (catalog now 22; note the OpenAI/Mantle path is a 3rd provider, frontend touchpoints differ slightly).

## 8. Verification plan (live-endpoint unknowns — test, don't assume)

1. **`max_tokens` vs `max_completion_tokens`** — gpt-5.x may require the latter. Probe once; on a param error, switch.
2. **`stream_options.include_usage`** — confirm Mantle returns a final usage chunk; without it input/output tokens (→ TPS, cost) are 0.
3. **Extra headers** — confirm bearer key alone suffices (no `anthropic-workspace-id`-style header).
4. After deploy: `curl …/api/auto-probe/latest` shows 4 OpenAI rows with non-null TTFT/tokens; `/cost` shows non-zero OpenAI cost; frontend cards grouped under OpenAI with green lines.

## 9. Out of scope

- Cached-input cost tracking (needs DB column + prober `usage.prompt_tokens_details.cached_tokens` + pricing schema change).
- OptimizePrompt support for OpenAI models.
- Changing the CDK `imageTag` policy (immutable-tag handled at register-task-definition time per ADR-018).

## 10. Risks

- (Verification #1/#2) wrong param / missing usage → silently 0 tokens. Mitigated by the verification step.
- A (region, model) combo not actually served → that channel shows error rows (acceptable; surfaces availability).
- Backend/frontend pricing-normalizer drift → mismatched cost. Mitigated by mirroring logic exactly + the in-file sync comments.
- Autoprober DB-session concurrency is bounded per-worker (v2.2.1 fix), independent of model count — 18 → 22 does not reintroduce pool exhaustion.
