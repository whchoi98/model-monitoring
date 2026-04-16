# Onboarding Guide — Bedrock LLM Monitor

## Prerequisites

- AWS account with Bedrock access (us-east-1, ap-northeast-2)
- EC2 instance access (SSH key)
- Python 3.9+ installed
- Node.js 18+ and npm installed
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
| `ADMIN_EMAIL` | Admin email for approval flow | `admin@example.com` |
| `DEFAULT_ADMIN_PASSWORD` | Initial admin password | `changeme` |
| `PUBLIC_BASE_URL` | Public URL for email links | `https://your-domain.com` |

## Key Concepts

- **Auto Prober**: Background daemon thread that probes all models every 5 minutes
- **Manual Probe**: Authenticated SSE streaming probe via `/api/probes/run`
- **Model Cards**: Dashboard grid showing latest metrics per model
- **Trend Charts**: Time-series visualization of TTFT, latency, and TPS

## Common Tasks

| Task | Command |
|------|---------|
| Restart backend | `sudo systemctl restart monitor-backend` |
| Restart frontend | `sudo systemctl restart monitor-frontend` |
| View backend logs | `journalctl -u monitor-backend -f` |
| Trigger probe | `curl -X POST http://localhost:8000/api/auto-probe/trigger` |
| Access DB | `docker exec -it monitoring-postgres psql -U postgres -d monitoring` |
