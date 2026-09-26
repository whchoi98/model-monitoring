# Backend Claude Features — Claude API feature × surface verification (v2.23.0)

## Role
Checks 39 documented Claude API features on 5 Claude-on-AWS surfaces for 5 representative models with real calls,
and compares each result with the documented expectation (drift). Results go to `feature_runs` / `feature_results`,
are served by `routers/features.py` and rendered on `/claude-features`. Design and drift history: ADR-026.

## Key Files
- `catalog.py` — `SURFACES` (`cp`, `mantle`, `bedrock_messages`, `bedrock_invoke`, `bedrock_converse`); `SURFACE_META` region env + default: `ANTHROPIC_AWS_REGION` us-east-2, `MANTLE_ANTHROPIC_REGION` us-east-1 (`parity/runner.py` falls back to ap-northeast-1 for the same env), `BEDROCK_FEATURES_REGION` ap-northeast-2. `MODELS` 5 (list order = UI chip order; Fable 5.1 has `mantle: None` — Mantle serves it only in US GovCloud). `FEATURES` 39 via `_f()`, where `bedrock_messages` inherits the `bedrock_invoke` expectation unless `_BEDROCK_MESSAGES_OVERRIDES` says otherwise. `is_applicable()` pre-decides cells in this order: no model id → not_applicable, `_CONVERSE_NOT_EXPRESSIBLE` (17 features, Converse only) → not_applicable, `_NOT_APPLICABLE_BY_DOC` (data_residency on the 4 AWS surfaces) → not_applicable, `_SKIPPED` (context_window_1m off CP) → skipped
- `transports.py` — no Anthropic SDK on purpose (`anthropic>=0.40.0` is unpinned; raw bodies isolate verdicts from SDK changes). `CpTransport` (x-api-key + `prober._anthropic_default_headers()`), `MantleTransport` and `BedrockMessagesTransport` (httpx, `aws_bedrock_token_generator.provide_token` bearer as x-api-key, one token per run), `BedrockInvokeTransport` / `BedrockConverseTransport` (boto3, read timeout 90 s, 2 attempts). Normalizes bedrock-runtime's HTTP 200 coral `UnknownOperationException` and off-route 403 "Authorization header is missing" to `TransportError(404)`. Thread-local `record_request` / `last_request` keep the last request body for failed-cell evidence
- `probes.py` — `PROBES` maps feature id → `fn(transport, model_id, model_key)` returning `(True | False | status, evidence)`; `run_probe` adds latency, classifies exceptions with `engine.classify`, and back-fills `evidence["request"]`. `_tool_choice` uses `parity.catalog.supports_forced_tool_choice` (auto + instruction for Fable 5.1 / Opus 5.5). `_ADVISOR_FOR` must cover every `MODEL_KEYS` entry. `CACHE_PAD` is deliberately bland prose — the old self-describing pad caused refusals and false broken cache cells. `fallback_credit` beta is `2026-07-01` on CP, `2026-06-01` on Mantle/Bedrock. MCP probe URL `FEATURES_MCP_SERVER_URL` is stored in public evidence (never put credentials in it); unreachable server → inconclusive
- `engine.py` — pure logic: `STATUSES` (6), `classify` (parity `classify_error` + `_EXTRA_UNSUPPORTED`), `verdict` (match / drift / undocumented / none), `aggregate_cell`, `diff_runs`, `change_kind` / `annotate_change_kinds` (pre-decided row = `latency_ms IS NULL AND error_message IS NULL`), `blocked_stop_reason` (refusal / content filter → inconclusive, not broken), `has_thinking_evidence` (signature-only thinking counts)
- `runner.py` — `CATALOG_VERSION`, `KEEP_RUNS = 60`, `_MAX_WORKERS = 4`. `build_jobs` → probes + pre-decided rows; a transport that fails to build marks every job on that surface broken (`transport init: …`); results are saved once on the main thread (no per-thread sessions); exceptions mark the run failed with `error_message`; pruning is separate and non-fatal. `smoke()` runs without a DB

## Rules
- Bump `runner.CATALOG_VERSION` whenever `_NOT_APPLICABLE_BY_DOC`, `documented` expectations, `_CONVERSE_NOT_EXPRESSIBLE`, `is_applicable` rules or `MODELS` change (root CLAUDE.md). Label/description text changes don't need it
- Adding a model: `MODELS` + `_ADVISOR_FOR` + `parity/catalog.py` `_NO_FORCED_TOOL_CHOICE_MARKERS` if forced `tool_choice` returns 400 + the cell-count pins in `tests/test_claude_features.py` (39 × 5 × 5 = 975, probes 813 + pre-decided 162)
- Suspect the probe first when a cell is broken: check the evidence snapshot (`/api/features/evidence`) before calling it a platform regression

## Commands
```bash
cd backend
python3.12 -m pytest tests/test_claude_features.py -q        # offline, no credentials
python -m features_runner --smoke --models sonnet-5 --surfaces cp,mantle [--features messages_basic] [--json]  # live, no DB
python -m features_runner --once                              # live + DB (scheduled task CMD)
```
