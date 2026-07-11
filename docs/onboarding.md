# Onboarding Guide — Bedrock LLM Monitor

## Prerequisites

- AWS account with Bedrock access (us-east-1, ap-northeast-2)
- Python 3.11+ installed
- Node.js 20+ and npm installed
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
- **Model Cards**: Dashboard grid showing latest metrics per model
- **Trend Charts**: Time-series visualization of TTFT, latency, and TPS
- **Model Explorer** (`/models`, v2.9.0): per-model cards with channel info, pricing, and copy-paste code examples per API (Converse / InvokeModel / Messages / Responses)
- **Parity Run** (`/parity`, v2.11.0): Fargate sweep every 12 hours probing model × API surface × feature with execution evidence — see `backend/parity/CLAUDE.md` and ADR-021
- **Comparison Lab**: one prompt → N models in parallel via `/api/compare/run` (SSE, auth)

## Common Tasks

> Production runs on ECS Fargate (not systemd/EC2). Use ECS, not `systemctl`.

| Task | Command |
|------|---------|
| Redeploy backend (prod) | `aws ecs update-service --cluster bedrock-monitor --service backend --force-new-deployment` |
| Redeploy frontend (prod) | `aws ecs update-service --cluster bedrock-monitor --service frontend --force-new-deployment` |
| View backend logs (prod) | `aws logs tail /ecs/backend --follow` |
| View autoprober logs | `aws logs tail /ecs/autoprober --since 1h` |
| View parity run logs | `aws logs tail /ecs/parityrun --since 1d` |
| Trigger probe (local) | `curl -X POST http://localhost:8000/api/auto-probe/trigger` |
| Access DB (local) | `docker exec -it monitoring-postgres psql -U postgres -d monitoring` |
