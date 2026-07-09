# ADR-020: OpenAI GPT monitoring via 1P direct (api.openai.com, 5th provider path)

- **Status**: Accepted
- **Date**: 2026-07-02
- **Supersedes**: —
- **Related**: ADR-019 (OpenAI via Bedrock Mantle, 4th path)

## Context

ADR-019 added OpenAI GPT monitoring through the **Bedrock Mantle** OpenAI-compatible
endpoint (`https://bedrock-mantle.<region>.api.aws/openai/v1`, Bedrock bearer token,
`openai.gpt-5.x` ids, per-region channels). The user requested monitoring the **first-party
(1P)** path — calling OpenAI's own API directly — to compare direct-vendor latency/behavior
against the AWS-brokered path (see benchmark memory `openai-gpt-ttfb-ttft-benchmark`: 1P
direct was ~2–3.5× faster on TTFB/TTFT in that measurement).

The 1P path differs from Mantle on three axes:

| | Bedrock Mantle (ADR-019) | **1P direct (this ADR)** |
|---|---|---|
| base_url | `https://bedrock-mantle.<region>.api.aws/openai/v1` | `https://api.openai.com/v1` |
| auth | Bedrock long-term bearer (`OPENAI_API_KEY`, `ABSK-…`) | **OpenAI platform key** (`OPENAI_1P_API_KEY`, `sk-proj-…`) |
| model id | `openai.gpt-5.4` | **`gpt-5.4`** (native, no prefix) |
| discriminator | AWS region | **none** — globally routed |
| API | Responses API (streaming) | **same** — reused verbatim |

> **Live finding (2026-07-02):** the two credentials are **not interchangeable** — the
> Bedrock bearer token returns `invalid_request_error: Incorrect API key provided` against
> api.openai.com. Separately, `insufficient_quota` is an **account (billing) property**, not
> a key property: one provided key failed on both models, another (funded) key invoked both
> `gpt-5.4` and `gpt-5.5` successfully (`status=completed`).

## Decision

Add a 5th provider path keyed by an `openai:1p:<native_id>` model-id prefix (pseudo-region
`1p`), reusing the existing `openai:` dispatch.

- `prober.py`:
  - `_openai_base_url("1p")` → `_openai_1p_base_url()` (env `OPENAI_1P_BASE_URL`, default
    `https://api.openai.com/v1`).
  - `_get_openai_client(base_url)` keeps its single-arg signature and selects the credential
    internally: 1P base_url → `OPENAI_1P_API_KEY`, else `OPENAI_API_KEY`. This keeps existing
    monkeypatch tests valid and leaves both probe call-sites untouched.
  - `_register_openai_models()` decouples the two paths — Mantle gated on `OPENAI_API_KEY`,
    1P gated independently on `OPENAI_1P_API_KEY` (`_OPENAI_1P_MODEL_SPECS`, native ids from
    `OPENAI_1P_GPT_54/55_MODEL_ID`).
  - The Responses-API streaming/stop-reason code from ADR-019 is reused unchanged (same API
    on both endpoints; gpt-5.x reject `/chat/completions` on both).
- `insufficient_quota` is deliberately **not** a retry marker — a billing failure must
  surface as `failed`, not be retried.
- Display label `OpenAI GPT 5.x (1P)`; `channelRank` already routes `OpenAI ` → tier 3.
- No pricing/cost/sort changes: `_normalize_key` collapses `openai:1p:gpt-5.x` → `gpt-5.x`,
  so 1P prices at the same rate as Mantle (a 1P-specific price is a deliberate follow-up).
- Secret `OPENAI_1P_API_KEY` via SSM SecureString `/bedrock-monitor/openai-1p-api-key`;
  model ids as plain env on backend + scheduler tasks. No new IAM (bearer auth).

Catalog: 26 → 28 (Bedrock 15 + Anthropic CP 6 + OpenAI 5 → 7).

## Consequences

- The dashboard can now compare the *same* GPT model across Mantle regions **and** the direct
  vendor path side by side.
- 1P channels depend on the OpenAI **account** having billing/quota; an unfunded key surfaces
  every 1P probe as `failed` (`insufficient_quota`) without affecting other channels.
- Cost figures for 1P currently reuse the Mantle price key — acceptable for latency/reliability
  monitoring; revisit if 1P vs Mantle cost comparison is needed.
- See memory `claude-on-aws-endpoint-model-id-matrix` / `adding-a-monitored-model` for the now
  five call paths and the full touchpoint checklist.
