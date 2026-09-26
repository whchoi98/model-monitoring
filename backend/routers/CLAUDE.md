# Backend Routers — API Endpoint Handlers

## Role
FastAPI router modules defining all API endpoints (18 router modules, registered in `main.py`; `pricing.py` holds two routers).
`GET /api/health` (public liveness, `{"status": "ok"}`) is defined in `backend/main.py`, not in a router.

## Files
- `auth.py` — `/api/auth/*` — login (public), register (EmailStr enforced), email approval, `/me` (JWT)
- `admin.py` — `/api/admin/*` — reset-monitoring-data, users CRUD (admin only: `username == "admin"`)
- `auto_probe.py` — `/api/auto-probe/*` — status (DB reservation + overdue state; `channel_intervals` / `channel_category_intervals` per-channel cadence, v2.29.0 — `{"anthropic": 300}` / `{"anthropic": 1800}` at the default since v2.29.1), latest (each model's latest row from completed auto runs within its own cadence window — `latest_results.py`, v2.29.0; not the rows of one run), trend, categories, anomalies?hours=&category= (automatic runs only) are public. `trigger` requires JWT and returns 202/409/503; scheduler/manual admission is serialized in `auto_prober.py`.
- `probes.py` — `/api/probes/run` — SSE streaming manual probe (JWT); `GET /api/probes/{run_id}` — past run + its results (public)
- `results.py` — `/api/results/*` — stored results query + stats (public)
- `models.py` — `/api/models` — `AVAILABLE_MODELS` list (public)
- `prompts.py` — `/api/prompts/*` — prompt set CRUD + `POST /api/prompts/optimize` Bedrock OptimizePrompt, synchronous JSON (list = public; create/delete/optimize = JWT)
- `chat.py` — `/api/chat/stream` — Sonnet 4.6 chatbot, 4 tools, dynamic followups (JWT)
- `insights.py` — `/api/insights/*` — list / latest (public); `POST /regenerate` (JWT, not streaming — starts a backend thread, returns `triggered` at once, lock-serialized) and `POST /stream-regenerate` (JWT, SSE)
- `compare.py` — `/api/compare/run` — Comparison Lab: 1 prompt → N models in parallel, SSE stream (JWT)
- `cost.py` — `/api/cost/*` — summary, channel-compare, trend; every row priced at the unit price in effect at its timestamp (`price_history.with_row_cost`, v2.30.0), a model without a price has a null cost, response shapes unchanged
- `reliability.py` — `/api/reliability/multi-channel` — family/channel success rate + error buckets
- `efficiency.py` — `/api/efficiency/score` — 0-100 weighted Token Efficiency Score per category (cost component = average per-row cost of priced success rows, v2.30.0)
- `pricing.py` — `router` `/api/pricing` (public, `build_pricing_payload`, 60 s in-process cache without `lang` in the key) and `/api/pricing/export?format=csv|md|json&lang=ko|en` (public, `Content-Disposition: attachment; filename="llm-monitor-unit-prices-YYYY-MM-DD.<ext>"`); `admin_router` `/api/admin/pricing/pending`, `POST /pending/{row_id}/approve`, `POST /pending/{row_id}/reject` (admin only, `effective_from` kept on approve, `warnings` when a verified price comes later in the lookup order `(effective_from, id)`, 404/409 with a Korean `detail`, `invalidate_cache()` after each — other backend tasks can lag up to 60 s; a generation counter keeps a payload built during a clear out of the cache) (v2.30.0, ADR-030)
- `analysis.py` — `/api/analysis/*` — stop-reason distribution + output-length histograms
- `parity.py` — `/api/parity/*` — catalog, latest (완료 런 매트릭스 + 직전 런 대비 changes diff, s-maxage=60), evidence (셀별 증거), trigger (JWT, backend 내 백그라운드 스레드 — 스케줄 런과 달리 Fargate 아님)
- `gptbench.py` — `/api/gptbench/*` — latest (최신 **완료** 사이클 채널 스코어 카드 — 시작 후 14분 지난 사이클만 완료, 18채널 v2.28.0, `fam_rank` Astra, Sol, Luna, Terra, 5.5, 5.4), trend?hours= (사이클×채널 median 시계열, `hours` 1~168 — UI 최대 7일, 집계 7컬럼만 튜플 조회. 공개 엔드포인트라 상한이 곧 1요청 메모리 상한이다: 720h 전체 ORM 로드는 18채널에서 ~1 GB RSS로 1 GiB 태스크 OOM 위험) (public, v2.18.0)
- `features.py` — `/api/features/*` — catalog (39행×5 surface 정의), latest (완료 런 매트릭스 + 직전 런 대비 diff(kind: catalog|measured — 신규 셀, 사전판정 행은 catalog, v2.24.0) + drift), evidence (셀별 요청 스냅샷·응답 신호), trigger (JWT, backend 내 백그라운드 스레드, 5모델 975셀 약 9분 — v2.28.0) (v2.23.0)

## Conventions
- All routers use `prefix="/api/..."` and appropriate `tags`
- Auth-required endpoints use `Depends(get_current_user)`; admin gated on `username == "admin"`
- HTML responses (approval pages) must escape user input with `html.escape()`
- Error messages are in Korean for user-facing responses
- **SSE endpoints** (`probes`, `chat`, `insights`, `compare`) yield pre-formatted
  `"event: X\ndata: Y\n\n"` strings, so they MUST return
  `StreamingResponse(media_type="text/event-stream")` — never `EventSourceResponse`
  (it re-wraps each string as another `data:` field → malformed/double-wrapped SSE). See ADR-007.

## Tests
- `backend/tests/`: `test_auto_probe_status.py`, `test_auto_probe_latest.py`, `test_auto_probe_trend.py` (auto_probe), `test_reliability.py`, `test_gptbench.py`, `test_visibility.py` (results + `(1P)` hiding), `test_claude_features.py` (`routers.features.build_latest_payload`), `test_cost_time_effective.py` (cost and efficiency at the price in effect at each row), `test_pricing_router.py` (`/api/pricing`, export, admin approval — v2.30.0)
- Run: `cd backend && python3.12 -m pytest tests/ -q` (Python 3.10+)
