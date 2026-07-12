# Backend Routers — API Endpoint Handlers

## Role
FastAPI router modules defining all API endpoints (15 routers, registered in `main.py`).

## Files
- `auth.py` — `/api/auth/*` — login (public), register (EmailStr enforced), email approval, `/me` (JWT)
- `admin.py` — `/api/admin/*` — reset-monitoring-data, users CRUD (admin only: `username == "admin"`)
- `auto_probe.py` — `/api/auto-probe/*` — status (DB-sourced), latest, trend, categories, trigger, anomalies?hours= (최근 실패 요약, 대시보드 배너용) (public)
- `probes.py` — `/api/probes/run` — SSE streaming manual probe (JWT)
- `results.py` — `/api/results/*` — stored results query + stats (public)
- `models.py` — `/api/models` — `AVAILABLE_MODELS` list (public)
- `prompts.py` — `/api/prompts/*` — prompt set CRUD + Bedrock OptimizePrompt (write = JWT)
- `chat.py` — `/api/chat/stream` — Sonnet 4.6 chatbot, 4 tools, dynamic followups (JWT)
- `insights.py` — `/api/insights/*` — list / latest / stream-regenerate (regenerate = JWT)
- `compare.py` — `/api/compare/run` — Comparison Lab: 1 prompt → N models in parallel, SSE stream (JWT)
- `cost.py` — `/api/cost/*` — summary, channel-compare, trend
- `reliability.py` — `/api/reliability/multi-channel` — family/channel success rate + error buckets
- `efficiency.py` — `/api/efficiency/score` — 0-100 weighted Token Efficiency Score per category
- `analysis.py` — `/api/analysis/*` — stop-reason distribution + output-length histograms
- `parity.py` — `/api/parity/*` — catalog, latest (완료 런 매트릭스 + 직전 런 대비 changes diff, s-maxage=60), evidence (셀별 증거), trigger (JWT, backend 내 백그라운드 스레드 — 스케줄 런과 달리 Fargate 아님)

## Conventions
- All routers use `prefix="/api/..."` and appropriate `tags`
- Auth-required endpoints use `Depends(get_current_user)`; admin gated on `username == "admin"`
- HTML responses (approval pages) must escape user input with `html.escape()`
- Error messages are in Korean for user-facing responses
- **SSE endpoints** (`probes`, `chat`, `insights`, `compare`) yield pre-formatted
  `"event: X\ndata: Y\n\n"` strings, so they MUST return
  `StreamingResponse(media_type="text/event-stream")` — never `EventSourceResponse`
  (it re-wraps each string as another `data:` field → malformed/double-wrapped SSE). See ADR-007.
