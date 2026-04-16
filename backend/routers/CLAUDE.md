# Backend Routers — API Endpoint Handlers

## Role
FastAPI router modules defining all API endpoints.

## Files
- `auth.py` — `/api/auth/*` — Login, register, email approval, current user
- `auto_probe.py` — `/api/auto-probe/*` — Status, latest, trend, trigger (public)
- `probes.py` — `/api/probes/run` — SSE streaming manual probe (auth required)
- `results.py` — `/api/results/*` — Query stored results (public)
- `models.py` — `/api/models` — Available model list (public)
- `prompts.py` — `/api/prompts/*` — Prompt set CRUD (write = auth required)

## Conventions
- All routers use `prefix="/api/..."` and appropriate `tags`
- Auth-required endpoints use `Depends(get_current_user)`
- HTML responses (approval pages) must escape user input with `html.escape()`
- Error messages are in Korean for user-facing responses
