# Backend — FastAPI + SQLAlchemy

## Role
REST API server for Bedrock LLM model monitoring. The auto-prober and insights jobs run as
separate scheduled Fargate tasks (reusing this image), NOT in-process.

## Tech Stack
- Python 3.11
- FastAPI + Uvicorn
- SQLAlchemy 2.0 ORM + PostgreSQL 16
- boto3 (AWS Bedrock converse_stream)
- passlib + bcrypt (>=4.0, <4.1) for password hashing
- python-jose for JWT

## Key Files
- `main.py` — App entrypoint, lifespan, DB migration, admin seeding
- `prober.py` — Core probe logic, `AVAILABLE_MODELS` dict (single source of truth)
- `auto_prober.py` — `run_cycle()` one-shot probe cycle (NOT a daemon; invoked by a scheduled Fargate task); a model past `PROBE_FUTURE_TIMEOUT_S` gets a cycle-written error row and the run still completes (v2.28.2)
- `auto_prober_runner.py` — CLI entrypoint: `python -m auto_prober_runner --once`; ends with `os._exit` so a stray thread cannot keep the task RUNNING (v2.28.2)
- `stream_watchdog.py` — **Probe wall-clock watchdog** (v2.28.2, moved from gptbench): `CallWatchdog` + `abort_stream` (socket shutdown, then close). prober wraps every probe stream with `PROBE_WALL_CLOCK_S` (default 90 s) → error row `WallClockTimeout: …`; per-model cycle timeout max(120, cap + 30) s
- `insights_runner.py` — CLI entrypoint for the scheduled Insights task
- `parity_runner.py` — CLI entrypoint for the ParityRun task (`rate(12 hours)`): `python -m parity_runner --once`
- `parity/` — 패리티 런 엔진: `catalog.py` (6 surface × 19 feature, `surfaces_for`/`is_applicable`/`_FEATURE_SURFACES`), `engine.py` (판정 순수 로직 — `classify_error`, 증거 검사), `probes.py` (surface별 실행기 + `_req_snapshot` 요청 증거, `max_tokens_for` 피처별 예산), `runner.py` (ThreadPoolExecutor 4, 결과 일괄 저장)
- `gptbench.py` / `gptbench_runner.py` — GPT on AWS 벤치 (`rate(15 minutes)`, `python -m gptbench_runner --once`, v2.18.0): `_BENCH_SPECS` 18채널(Mantle 인리전 11 + CRIS 7, GPT-6 Sol/Luna v2.28.0 — 목록 끝), 채널당 워밍업 1 + 10회 순차; 호출당 wall-clock watchdog(`GPT_BENCH_CALL_TIMEOUT`, 소켓 shutdown 후 close — v2.28.2부터 `stream_watchdog.py` 공용) + `max_retries=0`(v2.28.0), 사이클 데드라인 `GPT_BENCH_DEADLINE`(780초, v2.18.0부터). 채널 키/라벨은 prober 규약 재사용, prober에 모델을 추가해도 벤치에는 자동 반영되지 않는다
- `features_runner.py` — CLI entrypoint for the scheduled FeaturesVerify task (`rate(24 hours)`): `python -m features_runner --once` (v2.23.0)
- `claude_features/` — Claude API Features 검증 엔진: `catalog.py` (39행 = 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1; 5 surface — cp/mantle/bedrock_messages/bedrock_invoke/bedrock_converse, `documented_for`; 대표 `MODELS` 5종 — Opus 5.5 v2.28.0, 1런 975셀 = 프로브 813 + 사전판정 162, `MODELS` 변경 시 `runner.CATALOG_VERSION` 범프), `transports.py` (raw httpx CP/Mantle/bedrock-runtime Messages API + boto3 InvokeModel/Converse, SDK 미사용 — bedrock-runtime의 coral `UnknownOperationException`은 404로 정규화; 스레드 로컬 `record_request`/`last_request`로 마지막 요청 본문을 남겨 `run_probe`가 실패 셀 증거에 회수, v2.24.0), `probes.py` (피처별 프로브), `engine.py` (판정 순수 로직), `runner.py` (ThreadPoolExecutor 4, 60런 보존)
- `anomalies.py` — 최근 N시간 프로브 실패의 모델별 요약 (`/api/auto-probe/anomalies`, v2.12.0)
- `retention.py` — `RETENTION_DAYS` 초과 `probe_results` → `probe_results_hourly` 집계 이관
- `agent/` — chatbot core: `bedrock.py` (CHAT/INSIGHTS model IDs), `tools.py` (4 Bedrock tools), `memory.py` (AgentCore), `streaming.py`
- `auth.py` — JWT creation/validation, bcrypt hashing, environment config
- `models.py` — SQLAlchemy ORM models
- `schemas.py` — Pydantic response schemas
- `database.py` — DB connection, session factory
- `routers/` — API endpoint handlers (17 routers)

## Constraints
- `X | Y` union syntax is fine (Python 3.10+ runtime is 3.11)
- NO `from __future__ import annotations` in files with FastAPI dependencies (breaks FastAPI runtime type resolution; core non-FastAPI modules like `prober.py` may use it)
- bcrypt must be `>=4.0,<4.1` (passlib incompatibility with 5.x)
- All user input in HTML must use `html.escape()`
- Secrets must come from environment variables, never hardcoded
- New Bedrock models may deprecate parameters (e.g., Opus 4.7 → no temperature)
