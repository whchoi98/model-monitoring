# Backend — FastAPI + SQLAlchemy

## Role
REST API server for LLM channel monitoring (Amazon Bedrock, Claude Platform on AWS, OpenAI Mantle/CRIS). The auto-prober and insights jobs run as
separate scheduled Fargate tasks (reusing this image), NOT in-process.

## Tech Stack
- Python 3.11
- FastAPI + Uvicorn
- SQLAlchemy 2.0 ORM + PostgreSQL 16
- boto3 (AWS Bedrock converse_stream; `bedrock` `list_foundation_model_agreement_offers` and `pricing` `get_products` in us-east-1 for the price sync, v2.30.0)
- `anthropic` SDK — Claude Platform on AWS channels (`prober.py`, `parity/runner.py`)
- `openai` SDK — OpenAI Mantle in-region + Global/US CRIS (`prober.py`, `gptbench.py`, `parity/runner.py`)
- `aws-bedrock-token-generator` — SigV4-derived bearer for Mantle `/anthropic` (`parity/runner.py`, `claude_features/transports.py`)
- `httpx` — `claude_features/transports.py` raw HTTP transports, `pricing_sync.py` Anthropic `pricing.md` fetch (also FastAPI TestClient in `tests/`)
- passlib + bcrypt (>=4.0, <4.1) for password hashing
- python-jose for JWT
- `sse-starlette` is in `requirements.txt` but imported nowhere — SSE endpoints use `StreamingResponse` (ADR-007)

## Key Files
- `main.py` — App entrypoint, lifespan, DB migration, admin seeding
- `prober.py` — Core probe logic, `AVAILABLE_MODELS` dict (single source of truth). Monthly usage-cap 429 (`_is_usage_cap_error`: "usage limits" / "usage threshold" / `enforced_spend_limit_reached`) is never retried; the CP probe client `_get_anthropic_probe_client` has `max_retries=0` and the loop (`_should_retry_probe`) retries what the SDK used to (408/409/429/5xx, connection errors) — Comparison Lab and parity keep the SDK-default `_get_anthropic_client` (v2.29.0)
- `auto_prober.py` — `run_cycle()` one-shot probe cycle (NOT a daemon; invoked by a scheduled Fargate task); a model past `PROBE_FUTURE_TIMEOUT_S` gets a cycle-written error row and the run still completes (v2.28.2). `_plan_cycle` (v2.29.0; default every cycle again since v2.29.1): at the default CP interval (300 s = the base cadence) Claude Platform on AWS channels (`anthropic:*`) are probed every cycle with the cycle's preset and the CP history lookup is skipped; only when `ANTHROPIC_CP_PROBE_INTERVAL_S` exceeds the base cadence (e.g. 600) are they probed when the run holding their latest automatic row started ≥ interval − 150 s before the current run (run start, not row time), each with its own category rotation; every other model every cycle, `_next_preset` reads non-CP rows only
- `probe_cadence.py` — per-channel cadence (v2.29.0): `ANTHROPIC_CP_PROBE_INTERVAL_S` (default 300 = every cycle since v2.29.1, CDK-injected on the AutoProber task; 600 restores the v2.29.0 every-other-cycle mode; rounded to whole 5-minute cycles when read, ties down like the due check — 400 → 300, 700 → 600), `interval_for(model_id)`, `channel_intervals()` for `/api/auto-probe/status`
- `latest_results.py` — `latest_auto_rows` (v2.29.0): each model's latest row from completed automatic runs, window anchored at the latest completed run and sized by the model's cadence from `interval_for` (3 intervals, or 2 category rotations — 15 / 60 min for every channel at the default cadence) — shared by `/api/auto-probe/latest` and the chatbot `get_latest_results`
- `auto_prober_runner.py` — CLI entrypoint: `python -m auto_prober_runner --once`; ends with `os._exit` so a stray thread cannot keep the task RUNNING (v2.28.2)
- `stream_watchdog.py` — **Probe wall-clock watchdog** (v2.28.2, moved from gptbench): `CallWatchdog` + `abort_stream` (socket shutdown, then close). prober wraps every probe stream with `PROBE_WALL_CLOCK_S` (default 90 s) → error row `WallClockTimeout: …`; per-model cycle timeout max(120, cap + 30) s
- `insights_runner.py` — CLI entrypoint for the scheduled Insights task (`rate(5 minutes)`, `python -m insights_runner --window 6h`, `cdk/lib/stacks/scheduler-stack.ts`); model is Sonnet 4.6 via `agent/bedrock.py` `INSIGHTS_MODEL_ID` (`global.anthropic.claude-sonnet-4-6`)
- `parity_runner.py` — CLI entrypoint for the ParityRun task (`rate(12 hours)`): `python -m parity_runner --once`
- `parity/` — 패리티 런 엔진: `catalog.py` (6 surface × 19 feature, `surfaces_for`/`is_applicable`/`_FEATURE_SURFACES`), `engine.py` (판정 순수 로직 — `classify_error`, 증거 검사), `probes.py` (surface별 실행기 + `_req_snapshot` 요청 증거, `max_tokens_for` 피처별 예산), `runner.py` (ThreadPoolExecutor 4, 결과 일괄 저장)
- `gptbench.py` / `gptbench_runner.py` — GPT on AWS 벤치 (`rate(15 minutes)`, `python -m gptbench_runner --once`, v2.18.0): `_BENCH_SPECS` 18채널(Mantle 인리전 11 + CRIS 7, GPT-6 Sol/Luna v2.28.0 — 목록 끝), 채널당 워밍업 1 + 10회 순차; 호출당 wall-clock watchdog(`GPT_BENCH_CALL_TIMEOUT`, 소켓 shutdown 후 close — v2.28.2부터 `stream_watchdog.py` 공용) + `max_retries=0`(v2.28.0), 사이클 데드라인 `GPT_BENCH_DEADLINE`(780초, v2.18.0부터). 채널 키/라벨은 prober 규약 재사용, prober에 모델을 추가해도 벤치에는 자동 반영되지 않는다
- `features_runner.py` — CLI entrypoint for the scheduled FeaturesVerify task (daily `cron(30 17 * * ? *)` Etc/UTC = 02:30 KST — a fixed wall-clock time; `rate(24 hours)` would anchor to the schedule's creation time): `python -m features_runner --once` (v2.23.0)
- `claude_features/` — Claude API Features 검증 엔진: `catalog.py` (39행 = 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1; 5 surface — cp/mantle/bedrock_messages/bedrock_invoke/bedrock_converse, `documented_for`; 대표 `MODELS` 5종 — Opus 5.5 v2.28.0, 1런 975셀 = 프로브 813 + 사전판정 162, `MODELS` 변경 시 `runner.CATALOG_VERSION` 범프), `transports.py` (raw httpx CP/Mantle/bedrock-runtime Messages API + boto3 InvokeModel/Converse, SDK 미사용 — bedrock-runtime의 coral `UnknownOperationException`은 404로 정규화; 스레드 로컬 `record_request`/`last_request`로 마지막 요청 본문을 남겨 `run_probe`가 실패 셀 증거에 회수, v2.24.0), `probes.py` (피처별 프로브), `engine.py` (판정 순수 로직), `runner.py` (ThreadPoolExecutor 4, 60런 보존)
- `anomalies.py` — 최근 N시간 프로브 실패의 모델별 요약 (`/api/auto-probe/anomalies`, v2.12.0)
- `retention.py` — `RETENTION_DAYS` 초과 `probe_results` → `probe_results_hourly` 집계 이관
- **Unit prices (v2.30.0, ADR-030)** — `pricing.py` (`PRICE_TABLE`, `get_pricing`, `estimate_cost_usd`) is gone; prices live in the `price_history` table, one row per `model_id` and `effective_from`:
  - `pricing_sources.py` — pure data: `price_identity(model_id)` → `PriceIdentity(family_key, family, provider, channel, source_kind, source_ref)` or `None` (CP ids follow the prober `_ANTHROPIC_TARGETS` substring + `_is_point_release_of` rule, date suffixes included), `active_channels`, `tier_of`, `region_of`, `NOVA_USAGETYPES`, `ANTHROPIC_DOC_NAMES` (exact doc model names), `PROVIDER_ORDER`, `FAMILY_ORDER` (byte-identical to `frontend/src/lib/sortModels.ts`, pinned by pytest), `DISCLAIMER`, `OFFICIAL_PAGES`, `PRICE_NOTES` (manual GPT-5.6 Sol promo note)
  - `pricing_seed.py` — `SEED` (46 non-CP channels), `CP_SEED` (9 CP families by `family_key`), `seed_rows`, `ensure_seed(engine, active)`: per-`model_id` idempotent insert with `effective_from` 1970-01-01 and `status='seed'`, own transaction that sets `SET LOCAL statement_timeout` 30 s and `lock_timeout` 5 s, then takes `pg_advisory_xact_lock(917350003)` (PostgreSQL only); called after CP/OpenAI registration from the lifespan (failure does not stop startup) and from the runner
  - `pricing_parsers.py` — pure parsers: `single_public_offer`, `select_offer_price` (`DIMENSION_RE` allow-list, per-channel order), `parse_pricelist` (1K → 1M tokens), `parse_anthropic_pricing_md` (header names, `<sup>` stripped from name and value cells, exact names only); raise `PriceParseError` (Price List nested fields are type-checked too)
  - `pricing_sync.py` — `run_sync(session_factory, active, fetchers)`: `CHANGE_THRESHOLD` 0.5 inclusive (above → `pending_review`; a rejected or pending value is not raised twice), `SYNC_DEADLINE_S` 300 (`skipped:deadline`), `Fetchers` injected (`default_fetchers()` = boto3 bedrock/pricing in us-east-1 + httpx, 3 retries with backoff); observed prices quantized to 6 decimals (`PRICE_QUANTUM`) before compare and store, a positive value that rounds to 0 is a parse failure; a parser exception of any type skips only that source's (or FM id's) channels as `skipped:parse_failed`, only internal (DB) errors fail the run; never stores or logs `offerToken` or `legalTerm.url`
  - `pricing_sync_runner.py` — CLI entrypoint for the PricingSync task (`rate(12 hours)`): `python -m pricing_sync_runner --once` — `create_tables`, `_discover_anthropic_models`, `_register_openai_models`, `ensure_seed`, `run_sync` under `pg_advisory_lock(917350004)` (exits at once when the lock is held), ends with `os._exit`
  - `price_history.py` — `effective_prices_subquery` (`LEAD(effective_from)` per `model_id`), `with_row_cost(query)` (LEFT JOIN on `model_id` + time range, NULL without a price) used by `routers/cost.py` and `routers/efficiency.py`, `current_rows`, `pending_rows`, `last_finished_run`, `verification_of` (`seed_only` / `verified` / `stale`)
  - `pricing_payload.py` (`build_pricing_payload` — order, footnote numbers, references, `price_number`; `pending_review` counts distinct pending `model_id`s) and `pricing_export.py` (`to_json`, `to_markdown`, `to_csv` with a BOM and the disclaimer as one quoted `csv.writer` field on the first line, `export_filename`)
  - Adding a model: classify it in `pricing_sources.py` and seed it in `pricing_seed.py` — a test fails when an active channel has no identity or seed, and production shows a `no_baseline` pending row
- `label_repair.py` — startup label self-repair (v2.22.1): `repair_model_labels` (called from `main.py` lifespan, own transaction) rewrites stored `model_name` in `probe_results` / `probe_results_hourly` to the current `AVAILABLE_MODELS` label; model_ids outside the catalog are left alone
- `visibility.py` — `HIDDEN_MODEL_PATTERNS` (default `(1P)`) + `visible_only()` read filter used by the read routers, `latest_results.py`, `insights_runner.py` and chatbot tools; DB rows are kept (v2.19.1)
- `tests/` — offline pytest suite (`conftest.py` sets a test JWT key and a dead `DATABASE_URL`, tests use SQLite or fake sessions; price fixtures under `tests/fixtures/pricing/` carry no `offerToken`, `legalTerm.url` or presigned URLs)
- `agent/` — chatbot core: `bedrock.py` (CHAT/INSIGHTS model IDs), `tools.py` (4 Bedrock tools), `memory.py` (AgentCore), `streaming.py`
- `auth.py` — JWT creation/validation, bcrypt hashing, environment config
- `models.py` — SQLAlchemy ORM models (`PriceHistory`, `PriceSyncRun` since v2.30.0 — created by `create_all`, not the lifespan ALTER block)
- `schemas.py` — Pydantic response schemas
- `database.py` — DB connection, session factory
- `routers/` — API endpoint handlers (18 router modules)

## Commands
```bash
cd backend
python3.12 -m uvicorn main:app --host 0.0.0.0 --port 8000  # local run (needs JWT_SECRET_KEY + DATABASE_URL/DB_* env)
python3.12 -m pytest tests/ -q   # needs Python 3.10+ (CI uses 3.11); the dev host's system python3 is 3.9
ruff check .                     # = `make backend-lint` (`ruff check backend/` from the repo root; skipped when ruff is not installed, not run in CI)
```

## Constraints
- `X | Y` union syntax is fine (Python 3.10+ runtime is 3.11)
- `from __future__ import annotations` is allowed in FastAPI modules (most routers use it), but every type in an endpoint or `Depends` signature must then be a module-level name: a model defined inside a function or imported only under `TYPE_CHECKING` cannot be resolved from the string annotation, and FastAPI silently treats a body parameter as a required query parameter (422)
- bcrypt must be `>=4.0,<4.1` (passlib incompatibility with 5.x)
- SQLAlchemy must be `<2.1`: 2.1 makes psycopg (v3) the default driver for plain `postgresql://` URLs, and only `psycopg2-binary` is installed, so every DB import fails (CI 2026-09-26 with 2.1.1; production image runs 2.0.54). Moving to 2.1 means adding `psycopg[binary]` or writing `postgresql+psycopg2://` in `database.py`
- All user input in HTML must use `html.escape()`
- Secrets must come from environment variables, never hardcoded
- Timestamps are timezone-aware datetimes bound as ORM/Core parameters, never raw string literals in SQL (SQLite compares DateTime as text; `price_history` range joins depend on it)
- New Bedrock models may deprecate parameters (e.g., Opus 4.7 → no temperature)
