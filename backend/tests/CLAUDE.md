# Backend Tests — Offline pytest suite

## Role
29 `test_*.py` modules (430 tests) covering probe logic, cadence, watchdogs, catalogs, routers and migrations.
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
  - `test_fable51_catalog.py`, `test_opus55_gpt6_catalog.py`, `test_openai_pricing.py`, `test_label_repair.py` — model catalog labels, pricing keys, point-release matching
  - `test_claude_features.py`, `test_parity_logic.py`, `test_parity_openai_client.py` — verification engines (cell-count pins 813 + 162)

## Gotchas
- Needs Python ≥ 3.10 (FastAPI evaluates `X | Y` annotations at runtime). The dev host's `python3` is 3.9 and fails; use `python3.12`, which has the requirements installed
- Tests import backend modules by top-level name (`import models`, `from agent import tools`); pytest puts `backend/` on `sys.path` because `tests/` is a package and `backend/` is not
- Never make a test reach a provider: fake the SDK client or stream, as `test_probe_watchdog.py` and `test_openai_probe.py` do

## Commands
```bash
cd backend && python3.12 -m pytest tests/ -q          # full suite, ~8 s
python3.12 -m pytest tests/test_cp_cadence.py -q      # one module
```
