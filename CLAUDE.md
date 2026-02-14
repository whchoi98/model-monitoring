# CLAUDE.md — Project Context for Claude Code

## Project Overview

Bedrock LLM Monitor: AWS Bedrock 모델의 응답 속도, 처리량, 안정성을 실시간으로 모니터링하는 대시보드.

- **Backend**: FastAPI + SQLAlchemy ORM + PostgreSQL 16 (Docker)
- **Frontend**: Next.js 14 + React 18 + Tailwind CSS + Recharts
- **Infra**: EC2 (Amazon Linux 2023) + CloudFront + ALB + systemd

## Architecture

```
CloudFront (d1ra694ytoup3r.cloudfront.net)
    → ALB → EC2
        ├── Next.js 14 (port 3000) — /api/* proxied to backend
        ├── FastAPI (port 8000)
        │   ├── Auto Prober Thread (5min interval, 9 models, concurrency=3)
        │   └── PostgreSQL 16 (Docker, port 5432)
        └── AWS Bedrock (us-east-1) — converse_stream API
```

## Directory Structure

```
model-monitoring/
├── backend/
│   ├── main.py              # FastAPI entrypoint + lifespan (migration, auto_prober, admin seed)
│   ├── auto_prober.py       # Background thread: probes 9 models every 5 minutes
│   ├── prober.py            # Core probe logic (Bedrock converse_stream), AVAILABLE_MODELS dict
│   ├── auth.py              # JWT + bcrypt auth utilities, get_current_user dependency
│   ├── models.py            # SQLAlchemy models: ProbeRun, ProbeResult, PromptSet, User
│   ├── schemas.py           # Pydantic response schemas
│   ├── database.py          # DB connection (DATABASE_URL, SessionLocal, engine)
│   ├── requirements.txt     # Python dependencies
│   └── routers/
│       ├── auth.py          # /api/auth/* — login, register, approve, me
│       ├── auto_probe.py    # /api/auto-probe/* — status, latest, trend, trigger
│       ├── probes.py        # /api/probes/run — SSE streaming probe (auth required)
│       ├── results.py       # /api/results/* — query stored results
│       ├── models.py        # /api/models — available model list
│       └── prompts.py       # /api/prompts/* — prompt set CRUD (auth required)
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── page.tsx         # Main page: tabs (대시보드 / 수동 프로브), auth state
│   │   │   └── layout.tsx       # Root layout (lang="ko", Korean metadata)
│   │   ├── components/
│   │   │   ├── AutoDashboard.tsx    # Auto-probe dashboard (status bar + grid + charts)
│   │   │   ├── ModelStatusGrid.tsx  # 3x3 model status cards with color-coded metrics
│   │   │   ├── TrendChart.tsx       # Recharts LineChart (TTFT / latency / TPS)
│   │   │   ├── LoginForm.tsx        # Login + register form with approval-pending state
│   │   │   ├── ProbeRunner.tsx      # Manual probe execution UI
│   │   │   ├── ResultsTable.tsx     # Probe results table
│   │   │   └── ...
│   │   ├── hooks/
│   │   │   ├── useAutoRefresh.ts    # 30s auto-refresh with countdown
│   │   │   └── useProbeStream.ts    # SSE streaming hook for manual probes
│   │   └── lib/
│   │       ├── api.ts       # API client (auth token management, all fetch functions)
│   │       ├── i18n.ts      # Korean translations + metric descriptions
│   │       └── types.ts     # TypeScript interfaces
│   ├── next.config.ts       # API rewrites: /api/* → localhost:8000
│   ├── package.json
│   └── tailwind.config.ts
├── docker-compose.yml       # PostgreSQL container
├── deploy.sh                # One-click deployment script
└── cloudformation.yaml      # AWS CloudFormation template
```

## Key Commands

```bash
# Backend
cd backend && python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Frontend (dev)
cd frontend && npm run dev

# Frontend (production build)
cd frontend && npm run build && npm start

# PostgreSQL
docker compose up -d
docker exec monitoring-postgres pg_isready -U postgres

# Service management (production)
sudo systemctl restart monitor-backend
sudo systemctl restart monitor-frontend
journalctl -u monitor-backend -f
journalctl -u monitor-frontend -f

# Auto-probe status check
curl http://localhost:8000/api/auto-probe/status
curl http://localhost:8000/api/auto-probe/latest
curl -X POST http://localhost:8000/api/auto-probe/trigger

# DB direct access
docker exec -it monitoring-postgres psql -U postgres -d monitoring
```

## Monitored Models (9 total)

| Region | Models |
|--------|--------|
| US | Claude Opus 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5, Nova 2.0 Lite |
| Global | Claude Opus 4.6, Claude Opus 4.5, Claude Sonnet 4.5, Claude Haiku 4.5 |

Model list is defined in `backend/prober.py` → `AVAILABLE_MODELS` dict.

## Authentication System

- **JWT Bearer Token** (24h expiry), secret key via `JWT_SECRET_KEY` env var
- **Password hashing**: bcrypt via passlib (`bcrypt>=4.0,<4.1` pinned for compatibility)
- **Registration flow**: register → pending (approved=0) → admin email via SES → click approve link → approved (approved=1) → login allowed
- **Admin email**: `whchoi98@gmail.com` (configured in `backend/auth.py` → `ADMIN_EMAIL`)
- **Public base URL**: `https://d1ra694ytoup3r.cloudfront.net` (for approval email links)
- **Protected endpoints**: `/api/probes/run`, `/api/prompts` (POST/DELETE), `/api/auth/me`
- **Public endpoints**: `/api/auto-probe/*`, `/api/results/*`, `/api/models`
- Admin account seeded on first startup in `main.py` lifespan

## Database

- PostgreSQL 16 via Docker (`docker-compose.yml`)
- Connection: `postgresql://postgres:postgres@localhost:5432/monitoring`
- Tables: `probe_runs`, `probe_results`, `prompt_sets`, `users`
- Migrations run in `main.py` lifespan via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`

## Important Constraints

- **Python 3.9**: Do NOT use `X | Y` union syntax in type hints used by FastAPI dependencies. Use `Optional[X]` from typing instead. `from __future__ import annotations` breaks FastAPI's runtime type evaluation.
- **bcrypt version**: Must be `>=4.0,<4.1`. Version 5.x is incompatible with passlib.
- **Next.js API proxy**: All `/api/*` requests from the frontend are rewritten to `http://localhost:8000` via `next.config.ts` rewrites.
- **Korean UI**: All user-facing text is in Korean. Translations in `frontend/src/lib/i18n.ts`.
- **Auto-prober**: Runs as a daemon thread inside the FastAPI process. Not a separate service.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET_KEY` | `bedrock-monitor-secret-change-me` | JWT signing key |
| `PUBLIC_BASE_URL` | `https://d1ra694ytoup3r.cloudfront.net` | Base URL for email approval links |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/monitoring` | PostgreSQL connection |

## Git

- Remote: `https://github.com/whchoi98/model-monitoring.git`
- Branch: `main`
- Auth: `gh auth login` (GitHub CLI device code flow, user `whchoi98`)
