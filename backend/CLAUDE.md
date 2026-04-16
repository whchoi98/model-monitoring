# Backend — FastAPI + SQLAlchemy

## Role
REST API server + background auto-prober for Bedrock LLM model monitoring.

## Tech Stack
- Python 3.11 (must maintain 3.9 compatibility in type hints)
- FastAPI + Uvicorn
- SQLAlchemy 2.0 ORM + PostgreSQL 16
- boto3 (AWS Bedrock converse_stream)
- passlib + bcrypt (>=4.0, <4.1) for password hashing
- python-jose for JWT

## Key Files
- `main.py` — App entrypoint, lifespan, DB migration, admin seeding
- `prober.py` — Core probe logic, `AVAILABLE_MODELS` dict (single source of truth)
- `auto_prober.py` — 5-min interval daemon thread, singleton
- `auth.py` — JWT creation/validation, bcrypt hashing, environment config
- `models.py` — SQLAlchemy ORM models
- `schemas.py` — Pydantic response schemas
- `database.py` — DB connection, session factory
- `routers/` — API endpoint handlers

## Constraints
- NO `X | Y` union syntax — use `Optional[X]` (Python 3.9 compat)
- NO `from __future__ import annotations` in files with FastAPI dependencies
- bcrypt must be `>=4.0,<4.1` (passlib incompatibility with 5.x)
- All user input in HTML must use `html.escape()`
- Secrets must come from environment variables, never hardcoded
- New Bedrock models may deprecate parameters (e.g., Opus 4.7 → no temperature)
