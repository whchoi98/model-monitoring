# ADR-019: OpenAI GPT monitoring via Bedrock Mantle (4th provider path)

- **Status**: Accepted
- **Date**: 2026-06-26
- **Supersedes**: —

## Context

We monitored two call paths: boto3 Bedrock `converse_stream` (`global.*`/`us.*`) and
Anthropic CP-on-AWS (`anthropic:*`). The user requested monitoring OpenAI GPT-5.4 and
GPT-5.5, which AWS serves via the **Bedrock Mantle OpenAI-compatible endpoint**
(`https://bedrock-mantle.<region>.api.aws/openai/v1`) — OpenAI Chat Completions shape,
authed with a Bedrock long-term API key as a bearer token. Both models are monitored
in **us-east-1 and us-east-2** (4 channels), in-region (no cross-region profile).

## Decision

Add a 4th provider path keyed by an `openai:<region>:<actual_model_id>` model-id prefix.
- `prober.py` dispatches on the prefix; the OpenAI branch uses the `openai` SDK with a
  per-base-url client, native streaming for TTFT, and `stream_options.include_usage` for
  token counts. `finish_reason` is mapped to the existing stop-reason enum
  (stop→end_turn, length→max_tokens, tool_calls→tool_use, content_filter→content_filtered).
- gpt-5.x reasoning models: temperature is omitted; `max_completion_tokens` is tried first
  with a fallback to `max_tokens` (endpoint-dependent).
- New `OpenAI` display family (label `OpenAI GPT 5.x (<region>)`), its own cost channel.
- Pricing (USD/1M, input/output only; cached-input not tracked): GPT-5.4 2.75/16.50,
  GPT-5.5 5.50/33.00.
- Secret `OPENAI_API_KEY` via SSM SecureString `/bedrock-monitor/openai-api-key`; base URLs
  + model ids as plain env on both backend and scheduler tasks. No new IAM (bearer auth).

Catalog: 18 → 22 (Bedrock 13 + Anthropic CP 5 + OpenAI 4).

## Consequences

- Endpoint quirks (`max_tokens` vs `max_completion_tokens`, whether `include_usage` is
  honored) are verified live, not assumed (see plan Task 9). A (region, model) combo not
  actually served surfaces as error rows.
- See memory `claude-on-aws-endpoint-model-id-matrix` for the now-four call paths.
