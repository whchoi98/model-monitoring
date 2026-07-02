# Design: OpenAI GPT 1P (direct api.openai.com) monitoring channel

- **Date**: 2026-07-02
- **Branch**: `feat/openai-gpt-monitoring`
- **Version**: v2.6.0
- **Status**: Approved (design + deploy) — 2026-07-02

## Goal

Add **OpenAI GPT 5.4 (1P)** and **OpenAI GPT 5.5 (1P)** as monitored channels that call
OpenAI's **first-party** API (`https://api.openai.com/v1`) directly, distinct from the existing
Bedrock Mantle OpenAI path. Catalog **26 → 28** (OpenAI 5 → 7).

## Background: this is a 5th provider path

The existing `_is_openai_direct()` in `prober.py` is a misnomer — it is actually the **Bedrock
Mantle** path. The genuinely direct path differs on three axes:

| | Bedrock Mantle (existing) | **1P direct (new)** |
|---|---|---|
| base_url | `https://bedrock-mantle.<region>.api.aws/openai/v1` | `https://api.openai.com/v1` |
| auth | Bedrock long-term bearer (`OPENAI_API_KEY`, `ABSK-…`) | **OpenAI platform key `sk-proj-…` (`OPENAI_1P_API_KEY`)** |
| model id | `openai.gpt-5.4` | **`gpt-5.4`** (native, no prefix) |
| discriminator | AWS region (us-east-1/2/west-2) | **none** — globally routed |
| API | Responses API (streaming) | **same** — code reused verbatim |

The two credentials are **not interchangeable**: the Bedrock bearer token returns
`invalid_request_error: Incorrect API key provided` against api.openai.com (verified 2026-07-02).

## Verification (2026-07-02)

- Both `gpt-5.4` and `gpt-5.5` are visible in `/v1/models` on 1P.
- A funded `sk-proj-…` key invokes **both** successfully (Responses API, `status=completed`).
  An earlier key returned `insufficient_quota` — quota is an **account (billing) property**, not a
  key property. The working key must be stored in SSM and, ideally, rotated after setup (it was
  exposed in chat).

## Key scheme

`openai:1p:gpt-5.4` — reuse the `openai:` prefix with pseudo-region `1p`. This means the existing
normalizers work **unchanged**: `pricing.py`/`pricing.ts` `_normalize_key` collapse
`openai:1p:gpt-5.4` → `gpt-5.4`; `cost.py` `_channel()` buckets `openai:` → `OpenAI`;
`sortModels.ts` `channelRank` routes `OpenAI ` → tier 3.

## Canonical labels (byte-identical across backend + TrendChart)

- `OpenAI GPT 5.4 (1P)`
- `OpenAI GPT 5.5 (1P)`

## Changes

### Backend — `backend/prober.py` (3 localized edits)
1. `_openai_base_url(region)`: add `1p` branch → `_openai_1p_base_url()` (env `OPENAI_1P_BASE_URL`,
   default `https://api.openai.com/v1`).
2. `_get_openai_client(base_url)`: **keep single-arg signature**; select credential internally — if
   `base_url == _openai_1p_base_url()` use `OPENAI_1P_API_KEY`, else `OPENAI_API_KEY`. (Keeps the
   existing monkeypatch test valid; both probe call-sites unchanged.)
3. `_register_openai_models()`: decouple the two paths — register Mantle when `OPENAI_API_KEY` is
   set (unchanged), and register 1P from a new `_OPENAI_1P_MODEL_SPECS` when `OPENAI_1P_API_KEY` is
   set. 1P native ids come from `OPENAI_1P_GPT_54_MODEL_ID` / `OPENAI_1P_GPT_55_MODEL_ID`.

`insufficient_quota` is deliberately **not** added to retry markers — a billing failure must surface
as `failed`, not be retried.

### No change (verified)
`pricing.py`, `pricing.ts`, `cost.py`, `sortModels.ts`, `requirements.txt` (`openai>=1.0.0` present).
Caveat: 1P prices at the same `gpt-5.4`/`gpt-5.5` rate as Mantle; a 1P-specific price is a follow-up.

### Backend tests — `backend/tests/test_openai_probe.py`
Add: `_openai_base_url("1p")` (default + `OPENAI_1P_BASE_URL` override), `_openai_parts` on a 1p key,
and 1P registration (`openai:1p:gpt-5.4/5.5` labels, gated on `OPENAI_1P_API_KEY`, independent of
`OPENAI_API_KEY`).

### Frontend (3 files)
- `TrendChart.tsx`: +2 exact `MODEL_COLORS` entries (`OpenAI GPT 5.4 (1P)`, `OpenAI GPT 5.5 (1P)`).
- `StreamingView.tsx`: `extractModelName` maps region `1p` → `1P`; +2 `MODEL_COLORS` (`GPT 5.x (1P)`).
- `version.ts`: `APP_VERSION` → `v2.6.0`.

### CDK (2 stacks)
- `app-services-stack.ts` + `scheduler-stack.ts` `buildTaskDef`: import SSM SecureString
  `/bedrock-monitor/openai-1p-api-key` → secret `OPENAI_1P_API_KEY`; env
  `OPENAI_1P_GPT_54_MODEL_ID=gpt-5.4`, `OPENAI_1P_GPT_55_MODEL_ID=gpt-5.5`
  (+ optional `OPENAI_1P_BASE_URL`). No IAM/SigV4 (bearer auth).

### Docs
New **ADR-020** (1P direct path); CLAUDE.md table + counts (26→28); README (bilingual);
architecture.md; api-reference.md `model_count`; CHANGELOG v2.6.0; deploy runbook SSM pre-create step.

## Deploy (manual immutable-digest path, per runbook — NOT `cdk deploy`)
1. Create SSM SecureString `/bedrock-monitor/openai-1p-api-key` (funded key).
2. Add `ssm:GetParameters` on the new param ARN to `BackendExecRole` + Scheduler `TaskExecRole`.
3. Build/push ARM64 backend + frontend images (immutable `v<ts>` tag + `@sha256` digest).
4. Register new TD revisions (backend service + autoprober + insights) with new image + env + secret;
   update service + scheduler schedules (RunTask resource is family `:*` — ADR-011 safe).
5. CloudFront invalidate `/api/*`; trigger an immediate autoprober `run-task`; verify both 1P
   channels return `status: success` with non-zero tokens.

## Out of scope / follow-ups
- 1P-accurate pricing (currently shares Mantle price key).
- Pinned model snapshots (`gpt-5.4-2026-03-05`) — using floating `gpt-5.4`/`gpt-5.5`.
