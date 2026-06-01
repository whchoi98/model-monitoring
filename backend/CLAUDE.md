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
- `agent/` — chatbot core: `bedrock.py` (CHAT/INSIGHTS model IDs), `tools.py` (4 Bedrock tools), `memory.py` (AgentCore), `streaming.py`
- `auth.py` — JWT creation/validation, bcrypt hashing, environment config
- `models.py` — SQLAlchemy ORM models
- `schemas.py` — Pydantic response schemas
- `database.py` — DB connection, session factory
- `routers/` — API endpoint handlers (14 routers)

## Constraints
- `X | Y` union syntax is fine (Python 3.10+ runtime is 3.11)
- NO `from __future__ import annotations` in files with FastAPI dependencies (breaks FastAPI runtime type resolution; core non-FastAPI modules like `prober.py` may use it)
- bcrypt must be `>=4.0,<4.1` (passlib incompatibility with 5.x)
- All user input in HTML must use `html.escape()`
- Secrets must come from environment variables, never hardcoded
- New Bedrock models may deprecate parameters (e.g., Opus 4.7 → no temperature)
