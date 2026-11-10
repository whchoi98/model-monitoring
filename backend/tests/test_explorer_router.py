"""routers/explorer.py — /api/explorer/latest and /trigger on in-memory SQLite (v2.40.0, ADR-035)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
import prober
from auth import create_access_token
from database import get_db
from model_explorer import runner
from model_explorer.examples import code_examples
from routers import explorer as explorer_router

OPUS = "global.anthropic.claude-opus-5"
NOVA = "us.amazon.nova-2-lite-v1:0"
CP = "anthropic:claude-sonnet-5-5"
HIDDEN = "openai:1p:gpt-5.5"
MODELS = {OPUS: "Bedrock Claude Opus 5 (Global)", NOVA: "Bedrock Nova 2.0 Lite (US)",
          CP: "Anthropic Claude Sonnet 5.5 (US)", HIDDEN: "OpenAI GPT 5.5 (1P)"}
NOW = datetime.now(timezone.utc)


def _sha(model_id, api_id):
    return next(ex["code_sha"] for ex in code_examples(model_id) if ex["api_id"] == api_id)


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.delenv("HIDDEN_MODEL_PATTERNS", raising=False)
    monkeypatch.setattr(prober, "AVAILABLE_MODELS", dict(MODELS))
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add(models.User(username="viewer@example.com", password_hash="x", approved=1))
        db.commit()
    app = FastAPI()
    app.include_router(explorer_router.router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    explorer_router._running["active"] = False
    with TestClient(app) as client:
        yield factory, client
    engine.dispose()


def _add_run(factory, cells, *, status="completed", started=NOW - timedelta(hours=2), finished=True):
    """cells: [(model_id, api_id, status, code_sha or None for the current one)]"""
    with factory() as db:
        run = models.ExplorerRun(status=status, started_at=started,
                                 finished_at=started + timedelta(minutes=2) if finished else None,
                                 totals={"passed": 1, "failed": 0, "skipped": 0})
        db.add(run)
        db.flush()
        for model_id, api_id, cell_status, sha in cells:
            db.add(models.ExplorerResult(
                run_id=run.id, model_id=model_id, model_name=MODELS[model_id], api_id=api_id, status=cell_status,
                latency_ms=1180.0, attempts=1, code_sha=sha or _sha(model_id, api_id),
                output_excerpt="Hello!" if cell_status == "passed" else None,
                error_message=None if cell_status == "passed" else "KeyError: 'text'\nTraceback"))
        db.commit()
        return run.id


def test_no_run_yet_still_sends_every_visible_models_examples(env):
    _, client = env
    body = client.get("/api/explorer/latest").json()
    assert (body["run"], body["running"], body["previous_run_id"], body["changes"]) == (None, False, None, [])
    assert list(body["models"]) == [OPUS, NOVA, CP]
    opus = body["models"][OPUS]["examples"]
    assert [ex["api_id"] for ex in opus] == ["converse", "invoke_model", "messages"]
    assert opus[0]["code"]["en"] == code_examples(OPUS)[0]["code"]["en"] and opus[0]["result"] is None
    assert set(opus[0]["description"]) == {"ko", "en"}


def test_latest_attaches_the_completed_runs_result_and_cache_header(env):
    factory, client = env
    run_id = _add_run(factory, [(OPUS, "converse", "passed", None), (OPUS, "invoke_model", "failed", None)])
    response = client.get("/api/explorer/latest")
    assert response.headers["cache-control"] == "public, max-age=0, s-maxage=60"
    body = response.json()
    assert body["run"]["id"] == run_id and body["run"]["totals"] == {"passed": 1, "failed": 0, "skipped": 0}
    assert body["run"]["finished_at"].endswith("Z") and body["previous_run_id"] is None and body["changes"] == []
    converse, invoke, messages = body["models"][OPUS]["examples"]
    assert converse["result"] == {"status": "passed", "latency_ms": 1180.0, "attempts": 1, "error_message": None,
                                  "output_excerpt": "Hello!", "run_id": run_id,
                                  "verified_at": body["run"]["finished_at"], "stale_code": False}
    assert invoke["result"]["status"] == "failed" and invoke["result"]["error_message"].startswith("KeyError")
    assert messages["result"] is None


def test_a_result_measured_on_older_code_is_marked_stale(env):
    factory, client = env
    _add_run(factory, [(OPUS, "converse", "passed", "0" * 64)])
    assert client.get("/api/explorer/latest").json()["models"][OPUS]["examples"][0]["result"]["stale_code"] is True


def test_changes_have_three_kinds_and_ignore_cells_only_the_previous_run_had(env):
    factory, client = env
    previous = _add_run(factory, [
        (OPUS, "converse", "passed", None),          # unchanged
        (OPUS, "invoke_model", "passed", None),      # measured: passed -> failed
        (OPUS, "messages", "passed", "0" * 64),      # example: code changed, still passing
        (NOVA, "converse", "passed", None),          # gone from the current run: ignored
    ], started=NOW - timedelta(days=1))
    _add_run(factory, [
        (OPUS, "converse", "passed", None), (OPUS, "invoke_model", "failed", None),
        (OPUS, "messages", "passed", None), (CP, "messages", "passed", None),   # catalog: new cell
    ])
    body = client.get("/api/explorer/latest").json()
    assert body["previous_run_id"] == previous
    assert body["changes"] == [
        {"model_id": CP, "model_name": MODELS[CP], "api_id": "messages", "api": "Messages API",
         "before": None, "after": "passed", "kind": "catalog"},
        {"model_id": OPUS, "model_name": MODELS[OPUS], "api_id": "invoke_model", "api": "InvokeModel API",
         "before": "passed", "after": "failed", "kind": "measured"},
        {"model_id": OPUS, "model_name": MODELS[OPUS], "api_id": "messages", "api": "Messages API",
         "before": "passed", "after": "passed", "kind": "example"},
    ]


def test_failed_and_running_runs_are_not_the_latest(env):
    factory, client = env
    done = _add_run(factory, [(OPUS, "converse", "passed", None)], started=NOW - timedelta(days=1))
    _add_run(factory, [], status="failed", started=NOW - timedelta(hours=3))
    _add_run(factory, [], status="running", started=NOW - timedelta(minutes=5), finished=False)
    body = client.get("/api/explorer/latest").json()
    assert body["run"]["id"] == done and body["running"] is True


def test_a_running_row_older_than_30_minutes_is_not_running(env):
    factory, client = env
    _add_run(factory, [], status="running", started=NOW - timedelta(minutes=31), finished=False)
    assert client.get("/api/explorer/latest").json()["running"] is False


def test_hidden_models_are_left_out_of_models_and_changes(env):
    factory, client = env
    _add_run(factory, [(HIDDEN, "responses", "passed", None)], started=NOW - timedelta(days=1))
    _add_run(factory, [(HIDDEN, "responses", "failed", None)])
    body = client.get("/api/explorer/latest").json()
    assert HIDDEN not in body["models"] and body["changes"] == []


def test_a_thread_that_does_not_start_releases_the_run_flag(env, monkeypatch):
    """Thread.start() can raise RuntimeError (no thread left); the in-process flag must not stay set (PR #76 review)."""
    _, client = env
    headers = {"Authorization": f"Bearer {create_access_token('viewer@example.com')}"}

    class _NoThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("can't start new thread")

    monkeypatch.setattr(explorer_router, "threading", type("T", (), {"Thread": _NoThread}))
    assert client.post("/api/explorer/trigger", headers=headers).json() == {
        "triggered": False, "message": "검증 런을 시작하지 못했습니다"}
    assert explorer_router._running["active"] is False
    assert client.get("/api/explorer/latest").json()["running"] is False


def test_trigger_needs_a_login(env):
    _, client = env
    assert client.post("/api/explorer/trigger").status_code == 401


def test_trigger_starts_one_run_and_refuses_a_second(env, monkeypatch):
    factory, client = env
    started = []
    monkeypatch.setattr(runner, "run_explorer", lambda **kw: started.append(kw))
    headers = {"Authorization": f"Bearer {create_access_token('viewer@example.com')}"}
    explorer_router._running["active"] = True
    assert client.post("/api/explorer/trigger", headers=headers).json() == {
        "triggered": False, "message": "이미 실행 중입니다"}
    explorer_router._running["active"] = False
    _add_run(factory, [], status="running", started=NOW - timedelta(minutes=5), finished=False)
    assert client.post("/api/explorer/trigger", headers=headers).json()["triggered"] is False
    with factory() as db:
        db.query(models.ExplorerRun).delete()
        db.commit()
    body = client.post("/api/explorer/trigger", headers=headers).json()
    assert body == {"triggered": True, "message": "모델 탐색 검증 런을 시작했습니다 (약 2분 소요)"}
    for _ in range(100):
        if started and not explorer_router._running["active"]:
            break
        import time
        time.sleep(0.01)
    assert started == [{"max_workers": 2}] and explorer_router._running["active"] is False
    assert explorer_router.TRIGGER_MAX_WORKERS == 2
