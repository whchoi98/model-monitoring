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
- `auto_prober.py` — `run_cycle()` one-shot probe cycle (NOT a daemon; invoked by a scheduled Fargate task)
- `auto_prober_runner.py` — CLI entrypoint: `python -m auto_prober_runner --once`
- `insights_runner.py` — CLI entrypoint for the scheduled Insights task
- `parity_runner.py` — CLI entrypoint for the ParityRun task (`rate(12 hours)`): `python -m parity_runner --once`
- `parity/` — 패리티 런 엔진: `catalog.py` (6 surface × 19 feature, `surfaces_for`/`is_applicable`/`_FEATURE_SURFACES`), `engine.py` (판정 순수 로직 — `classify_error`, 증거 검사), `probes.py` (surface별 실행기 + `_req_snapshot` 요청 증거, `max_tokens_for` 피처별 예산), `runner.py` (ThreadPoolExecutor 4, 결과 일괄 저장)
- `features_runner.py` — CLI entrypoint for the scheduled FeaturesVerify task (`rate(24 hours)`): `python -m features_runner --once` (v2.23.0)
- `claude_features/` — Claude API Features 검증 엔진: `catalog.py` (39행 = 문서 피처 33 + 코어 4 + Models API 1 + strict_tool_use 분할 1; 5 surface — cp/mantle/bedrock_messages/bedrock_invoke/bedrock_converse, `documented_for`), `transports.py` (raw httpx CP/Mantle/bedrock-runtime Messages API + boto3 InvokeModel/Converse, SDK 미사용 — bedrock-runtime의 coral `UnknownOperationException`은 404로 정규화), `probes.py` (피처별 프로브), `engine.py` (판정 순수 로직), `runner.py` (ThreadPoolExecutor 4, 60런 보존)
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
