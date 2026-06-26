# ADR-019: OpenAI GPT monitoring via Bedrock Mantle (4th provider path)

- **Status**: Accepted
- **Date**: 2026-06-26
- **Supersedes**: —

## Context

We monitored two call paths: boto3 Bedrock `converse_stream` (`global.*`/`us.*`) and
Anthropic CP-on-AWS (`anthropic:*`). The user requested monitoring OpenAI GPT-5.4 and
GPT-5.5, which AWS serves via the **Bedrock Mantle OpenAI-compatible endpoint**
(`https://bedrock-mantle.<region>.api.aws/openai/v1`), authed with a Bedrock long-term
API key as a bearer token. Both models are monitored in **us-east-1 and us-east-2**
(4 channels), in-region (no cross-region profile).

> **Live finding (2026-06-26):** gpt-5.4/5.5 return `400 validation_error: "The model
> 'openai.gpt-5.x' does not support the '/v1/chat/completions' API"`. They are reasoning
> models and require the OpenAI **Responses API** (`/v1/responses`,
> `client.responses.create`), NOT Chat Completions. The initial implementation assumed
> Chat Completions and was corrected after live verification.

## Decision

Add a 4th provider path keyed by an `openai:<region>:<actual_model_id>` model-id prefix.
- `prober.py` dispatches on the prefix; the OpenAI branch uses the `openai` SDK's
  **Responses API** (`client.responses.create(input=…, max_output_tokens=…, stream=True)`)
  with a per-base-url client. Streaming events `response.output_text.delta` give TTFT +
  tokens; `response.completed`/`response.incomplete` carry `usage.input_tokens` /
  `usage.output_tokens`. stop_reason derives from the response `status`
  (`completed`→end_turn) and `incomplete_details.reason`
  (`max_output_tokens`→max_tokens, `content_filter`→content_filtered).
- gpt-5.x reasoning models: temperature is omitted; the token cap is `max_output_tokens`.
- New `OpenAI` display family (label `OpenAI GPT 5.x (<region>)`), its own cost channel.
- Pricing (USD/1M, input/output only; cached-input not tracked): GPT-5.4 2.75/16.50,
  GPT-5.5 5.50/33.00.
- Secret `OPENAI_API_KEY` via SSM SecureString `/bedrock-monitor/openai-api-key`; base URLs
  + model ids as plain env on both backend and scheduler tasks. No new IAM (bearer auth).

Catalog: 18 → 22 (Bedrock 13 + Anthropic CP 5 + OpenAI 4).

## Consequences

- Endpoint quirks are verified live, not assumed (see plan Task 9): live verification
  caught the Chat-Completions-unsupported error and confirmed the Responses API returns
  non-zero `usage` tokens. A (region, model) combo not actually served surfaces as error rows.
- Verified live 2026-06-26: all 4 channels `status: success`, non-zero input/output tokens
  (e.g. GPT-5.5 us-east-1: 75 in / 116 out, TTFT ~2.7s).
- See memory `claude-on-aws-endpoint-model-id-matrix` for the now-four call paths.
