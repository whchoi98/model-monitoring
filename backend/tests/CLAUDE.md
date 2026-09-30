# Backend Tests — Offline pytest suite

## Role
`test_*.py` modules covering probe logic, cadence, watchdogs, catalogs, unit prices, routers and migrations.
No network, no AWS credentials, no PostgreSQL. CI runs the same suite on Python 3.11 (`.github/workflows/ci.yml`).

## Key Files
- `conftest.py` — import-time env only: a test `JWT_SECRET_KEY`, a `DATABASE_URL` pointing at a closed port (`127.0.0.1:1`) so nothing inherits a real DB, and `AWS_EC2_METADATA_DISABLED=true`. No shared fixtures
- DB-backed tests build their own SQLite engine (`sqlite://` + `StaticPool`, e.g. `test_auto_probe_latest.py`, `test_agent_tools.py`) and monkeypatch `SessionLocal` / `get_db`; `test_auto_prober_timeout.py` uses a file-backed SQLite in `tmp_path` because worker threads need separate connections
- Router tests use FastAPI `TestClient` (`test_auto_probe_*`, `test_gptbench.py`, `test_visibility.py`); async helpers use `@pytest.mark.asyncio` (`test_streaming.py`)
- Incident pins — read the module docstring before changing the code it guards:
  - `test_cp_cadence.py` / `test_auto_probe_latest.py` — CP cadence knob: every cycle at the default 300 s (v2.29.1), and at 600 s every other cycle decided from the run start (`ProbeRun.created_at`); per-model latest rows (v2.29.0)
  - `test_cp_usage_cap.py` — monthly usage-cap 429 is never retried, ordinary transient errors still are; `_sdk_http_module()` builds mocks with the SDK's own HTTP library (anthropic 0.x → `httpx`, 1.x → `httpx2`; passing an `httpx.Client` to 1.x is a TypeError)
  - `test_auto_prober_timeout.py`, `test_auto_prober_runner.py`, `test_probe_watchdog.py`, `test_stream_watchdog.py` — one hung model yields an error row, the run completes, the runner exits via `os._exit` (2026-09-23)
  - `test_auto_prober_pool.py`, `test_database_config.py` — DB pool exhaustion incidents (2026-06-09, 2026-07-08)
  - `test_startup_migration.py`, `test_perf_indexes.py` — source-level guards on lifespan migration cost and index declarations
  - `test_fable51_catalog.py`, `test_opus55_gpt6_catalog.py`, `test_label_repair.py` — model catalog labels, seed prices and `price_identity` classification, point-release matching
  - `test_sonnet55_gpt61_inregion_catalog.py` (v2.32.0, ADR-031) — Seoul in-region keys: `_bedrock_target` region and stripped FM id together (dashboard probe, Comparison Lab, parity `_execute`, OptimizePrompt target), broken keys fall back without raising, temperature suppression, parity rows without `messages_mantle`; Claude Sonnet 5.5 Global only and its CP target right before `sonnet-5` (2026-09-30 CP model order labels every id once); GPT 6.1 Sol first in `_OPENAI_MODEL_SPECS`, exactly three channels, skipped without its env, no marker collision with GPT 6 Sol
  - `test_pricing_sources.py`, `test_pricing_seed.py`, `test_pricing_parsers.py`, `test_pricing_sync.py`, `test_pricing_sync_runner.py`, `test_price_history.py`, `test_cost_time_effective.py`, `test_openai_pricing.py`, `test_pricing_payload.py`, `test_pricing_export.py`, `test_pricing_router.py`, `test_pricing_columns.py` (v2.31.0: `ensure_price_columns` idempotence, the PostgreSQL `SET LOCAL` + `ADD COLUMN IF NOT EXISTS` path, the lifespan block-order guard, the background retry: no thread on a first-attempt success, `price-schema-retry` on a column or seed failure, both steps rerun with the same active set, stop at the first success, give up after the last attempt), `test_pricing_seed_extras.py` (v2.31.0: `seed_extra` values, extras on new seed rows, the `COALESCE` fill of NULL extra columns on existing seed rows) — unit prices (v2.30.0, ADR-030; cache, long-context and OpenAI official prices v2.31.0): offline parser fixtures in `fixtures/pricing/` (regenerated from the 2026-09-27 sources, with `openai_pricing.md`; the Claude Opus 5, Sonnet 5, Sonnet 5.5 and GPT 6.1 Sol offers and the Sonnet 5.5 and gpt-6.1-sol doc rows are 2026-09-30; no `offerToken`, `legalTerm.url` or presigned URLs), offer cache and `_long_ctx` dimensions with `cache_read_tokens` over `cached_input_tokens`, `enriched` fills and the per-field 50% gate, `ensure_price_columns` idempotence, sync thresholds (0.5 inclusive: 22 → 33 verified, 22 → 33.01 pending), 6-decimal quantization and zero-rounding rejection, any parser exception → `skipped:parse_failed`, seed coverage of every active channel, time-effective cost joins and the v2.29.1 equivalence copy, `/api/pricing` and export goldens, backend `FAMILY_ORDER` = `frontend/src/lib/sortModels.ts`, `OFFICIAL_LINKS` = `frontend/src/components/PricingPanel.tsx` `OFFICIAL_LINKS` (v2.31.1), the cited-references invariant on a production-shaped payload built from the real seeds of the 62 active channels plus the 9 OpenAI official prices (reference numbers = cell footnotes plus note references, 1..N, 23 references, v2.32.0; 21 in v2.31.1), `_plausible_long` (an offer or doc long-context price below the short-context price drops the long fields with a warning, no run error, v2.32.0), Seoul in-region `APN2_*_standard` from the real 2026-09-30 rate cards, GPT US CRIS seed = In Region seed on every price (v2.31.1). Shared data modules `pricing_catalog.py` (the 62 active channels, v2.32.0), `_pricing_dataset.py` (payload and export golden dataset) and `_legacy_pricing_v2291.py` (frozen v2.29.1 price table, equivalence test only) are not collected
  - `test_claude_features.py`, `test_parity_logic.py`, `test_parity_openai_client.py` — verification engines (cell-count pins 946 + 224 since v2.32.0, Sonnet 5.5 133 + 62)

## Gotchas
- Needs Python ≥ 3.10 (FastAPI evaluates `X | Y` annotations at runtime). The dev host's `python3` is 3.9 and fails; use `python3.12`, which has the requirements installed
- Tests import backend modules by top-level name (`import models`, `from agent import tools`); pytest puts `backend/` on `sys.path` because `tests/` is a package and `backend/` is not
- Never make a test reach a provider: fake the SDK client or stream, as `test_probe_watchdog.py` and `test_openai_probe.py` do

## Commands
```bash
cd backend && python3.12 -m pytest tests/ -q          # full suite, ~8 s
python3.12 -m pytest tests/test_cp_cadence.py -q      # one module
```
