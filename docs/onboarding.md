# Onboarding Guide — Bedrock LLM Monitor

## Prerequisites

- AWS account with Bedrock access (us-east-1, ap-northeast-2)
- Python 3.11+ installed (production and CI run 3.11; on the dev host the system `python3` is 3.9, so use `python3.12`)
- Node.js 20.9+ and npm installed
- Docker and docker compose installed

## Local Development Setup

### 1. Clone the repository
```bash
git clone https://github.com/whchoi98/model-monitoring.git
cd model-monitoring
```

### 2. Start PostgreSQL
```bash
docker compose up -d
docker exec monitoring-postgres pg_isready -U postgres
```

### 3. Backend setup
```bash
cd backend
cp ../.env.example .env   # Edit with your values
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 4. Frontend setup
```bash
cd frontend
npm install
npm run dev
```

### 5. Access the dashboard
- Frontend: http://localhost:3000
- Backend API: http://localhost:8000/docs (Swagger UI)

## Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `JWT_SECRET_KEY` | JWT signing key (required) | `your-secret-key-here` |
| `DATABASE_URL` | PostgreSQL connection | `postgresql://postgres:yourpass@localhost:5432/monitoring` |
| `SEED_ADMIN_USERNAME` | Seed admin username | `admin` |
| `SEED_ADMIN_PASSWORD` | Initial admin password (8+ chars) | `changeme123` |
| `PUBLIC_BASE_URL` | Public URL for email links | `https://your-domain.com` |

> `ADMIN_EMAIL` is hardcoded in `backend/auth.py` (`whchoi98@gmail.com`), not an env var.

## Key Concepts

- **Auto Prober**: Separate Fargate task (EventBridge Scheduler, every 5 min) that probes all models — `run_cycle()` in `auto_prober.py`, NOT an in-process daemon
- **Manual Probe**: Authenticated SSE streaming probe via `/api/probes/run`
- **Model Cards**: Catalog coverage, current failures, stale results and unmeasured channels; search/filter/sort and select cards to compare trends. TTFT / total latency / TPS values are graded per workload category — blue normal, amber ▲ warning, rose ◆ critical; thresholds live in `frontend/src/lib/metricGrade.ts` (v2.28.0, ADR-029).
- **Trend Charts**: Actual elapsed time with explicit gaps for failed or missing measurements. Filter/selection state is preserved in dashboard URLs.
- **Shared UI**: Public pages render during sign-in checks. Failed reads keep same-query cached results with a warning and retry; a changed filter cannot display an older query's data.
- **Model Explorer** (`/models`, v2.9.0): per-model cards with channel info, unit prices from `/api/pricing`, and copy-paste code examples per API (Converse / InvokeModel / Messages / Responses)
- **Unit Prices** (`/pricing`, v2.30.0; v2.31.0 adds prompt-caching prices on every channel, GPT long-context prices and an OpenAI official price column): Standard input/output price per model family and channel with source footnotes and CSV / Markdown / JSON download. The PricingSync Fargate task refreshes prices from official sources every 12 hours into `price_history`; costs use the price in effect at each probe's time, and a change above 50% waits for admin approval — see ADR-030
- **Parity Run** (`/parity`, v2.11.0): Fargate sweep every 12 hours probing model × API surface × feature with execution evidence — see `backend/parity/CLAUDE.md` and ADR-021
- **Comparison Lab**: one prompt → N models in parallel via `/api/compare/run` (SSE, auth)
- **GPT on AWS** (`/gpt-on-aws`, v2.18.0): GPT TTFB/TTFT bench on 21 channels every 15 minutes (GptBench Fargate task, parallel lanes per host) — see `backend/gptbench.py`
- **Claude API Features** (`/claude-features`, v2.23.0): daily (17:30 UTC) execution-evidence sweep of 39 rows × 5 surfaces × 7 representative models (1365 cells since v2.33.0) — see `backend/claude_features/CLAUDE.md` and ADR-026
- **Insights**: Sonnet 4.6 KO and EN summaries every 5 minutes (Insights Fargate task, `insights_runner.py`)
- **Channels**: 66 active channels (v2.33.0) — Bedrock Global, US and Seoul in-region (`bedrock:<region>:<fm-id>` keys, ADR-031), Claude Platform on AWS, OpenAI Mantle and Global/US CRIS; adding a model touches both `backend/prober.py` and the pricing tables (`pricing_sources.py`, `pricing_seed.py`)

## Common Tasks

> Production runs on ECS Fargate (not systemd/EC2). Use ECS, not `systemctl`.

| Task | Command |
|------|---------|
| Redeploy backend (prod) | `aws ecs update-service --cluster bedrock-monitor --service backend --force-new-deployment` |
| Redeploy frontend (prod) | `aws ecs update-service --cluster bedrock-monitor --service frontend --force-new-deployment` |
| View backend logs (prod) | `aws logs tail /ecs/backend --follow` |
| View autoprober logs | `aws logs tail /ecs/autoprober --since 1h` |
| View parity run logs | `aws logs tail /ecs/parityrun --since 1d` |
| View price sync logs | `aws logs tail /ecs/pricingsync --since 13h` |
| View GPT bench logs | `aws logs tail /ecs/gptbench --since 1h` |
| View Claude API Features logs | `aws logs tail /ecs/features --since 1d` |
| View insights logs | `aws logs tail /ecs/insights --since 1h` |
| Run backend tests | `cd backend && python3.12 -m pytest tests/ -q` |
| Run every local check (CDK, backend, frontend; no e2e) | `make verify` |
| Trigger probe (local, JWT) | `curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/auto-probe/trigger` |
| Access DB (local) | `docker exec -it monitoring-postgres psql -U postgres -d monitoring` |

## UI regression checks

```bash
cd frontend
npm ci
npx playwright install --with-deps chromium webkit
npm test
npm run test:e2e
# Run the same browser flows against a production build:
npm run build
PLAYWRIGHT_USE_PRODUCTION=1 npm run test:e2e
```

Browser tests intercept API requests and use fixtures. They do not start paid
probes or write monitoring data. Stop a development server on port 3100 before
using production mode; the local test runner reuses an existing server.
