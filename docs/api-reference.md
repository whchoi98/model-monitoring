# API Reference — Bedrock LLM Monitor

Base URL: `http://localhost:8000` (dev) | `https://llm-monitor.whchoi.net` (prod)

## Authentication

### POST /api/auth/login
Login and receive JWT token. Only approved accounts can login.

**Request:**
```json
{ "username": "string", "password": "string" }
```

**Response (200):**
```json
{ "access_token": "string", "token_type": "bearer", "username": "string" }
```

### POST /api/auth/register
Register a new account (starts in pending approval state).

**Request:**
```json
{ "username": "string (2-50 chars)", "password": "string (4-100 chars)" }
```

**Response (201):**
```json
{ "id": 1, "username": "string", "approved": 0 }
```

### GET /api/auth/approve?token=TOKEN
One-click approval link (sent to admin via email). Returns HTML response.

### GET /api/auth/me
**Auth required.** Returns current user info.

---

## Auto Probe (Public)

### GET /api/auto-probe/status
Returns auto-prober state.

**Response:**
```json
{
  "is_running": true,
  "current_cycle_running": false,
  "last_run_time": "2026-04-16T16:48:53Z",
  "next_run_time": "2026-04-16T16:53:53Z",
  "interval_seconds": 300,
  "model_count": 15
}
```

### GET /api/auto-probe/latest
Returns the most recent probe result for each model.

### GET /api/auto-probe/trend?hours=24
Returns time-series data. Default: 24 hours. Supported: 1, 3, 6, 12, 24, 72, 168.

### POST /api/auto-probe/trigger
Trigger an immediate probe cycle.

---

## Manual Probe (Auth Required)

### POST /api/probes/run
**Auth required.** SSE streaming probe execution.

**Request:**
```json
{
  "model_ids": ["us.anthropic.claude-opus-4-7"],
  "prompt": "Hello",
  "temperature": 0.7,
  "max_tokens": 256,
  "repeat_count": 1
}
```

**Response:** Server-Sent Events stream with progress and results.

---

## Models (Public)

### GET /api/models
Returns available model list.

**Response:**
```json
[
  { "id": "us.anthropic.claude-opus-4-8", "name": "Bedrock Claude Opus 4.8 (US)" },
  { "id": "us.anthropic.claude-opus-4-7", "name": "Bedrock Claude Opus 4.7 (US)" }
]
```

---

## Results (Public)

### GET /api/results?model_id=X&limit=50&offset=0
Query stored probe results with optional filters.

### GET /api/results/latest
Latest results across all models.

### GET /api/results/stats
Statistics: avg, p50, p95, p99 per model.

---

## Prompt Sets (Auth Required for write)

### GET /api/prompts
List all prompt sets.

### POST /api/prompts
**Auth required.** Create a prompt set.

### DELETE /api/prompts/{id}
**Auth required.** Delete a prompt set.
