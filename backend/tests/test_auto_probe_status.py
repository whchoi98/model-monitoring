"""DB-backed monitoring status, scoped anomalies, and authenticated admission.

All records live in SQLite memory. Probe threads are deferred so even a broken
authorization check cannot invoke a provider.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import auto_prober as worker
import models
from database import get_db
from routers import auto_probe

NOW = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
MODEL_NAME = "Bedrock Audit (Global)"
MODEL_ID = "global.anthropic.audit"


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    deferred = []

    class DeferredThread:
        def __init__(self, target, args=(), kwargs=None, **options):
            self.target, self.args, self.kwargs = target, args, kwargs or {}

        def start(self):
            deferred.append(self)

    monkeypatch.setattr(worker, "SessionLocal", factory)
    # Replace only the worker's module reference, not threading.Thread globally:
    # TestClient and ThreadPoolExecutor still need real threads.
    monkeypatch.setattr(worker, "threading", SimpleNamespace(Thread=DeferredThread))
    monkeypatch.setattr(worker, "datetime", FrozenDateTime)
    monkeypatch.setattr(auto_probe, "datetime", FrozenDateTime)
    monkeypatch.setattr(worker, "AVAILABLE_MODELS", {
        MODEL_ID: MODEL_NAME,
        "us.anthropic.audit": "Bedrock Audit (US)",
        "openai:1p:audit": "OpenAI Audit (1P)",
    })
    monkeypatch.setattr(worker.auto_prober, "current_cycle_running", False)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    monkeypatch.setenv("RETENTION_DAYS", "0")

    def forbid_provider(*args, **kwargs):
        raise AssertionError("A provider must never be called by API tests")

    monkeypatch.setattr(worker, "_get_bedrock_client", forbid_provider)
    monkeypatch.setattr(worker, "_probe_single_model", forbid_provider)

    app = FastAPI()
    app.include_router(auto_probe.router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    with factory() as db:
        db.add(models.User(username="audit", password_hash="unused", approved=1))
        db.add(models.User(username="pending", password_hash="unused", approved=0))
        db.commit()

    with TestClient(app) as client:
        yield SimpleNamespace(
            factory=factory,
            client=client,
            deferred=deferred,
            headers={"Authorization": f"Bearer {auth.create_access_token('audit')}"},
        )
    engine.dispose()


def seed(env, *, age=60, status="completed", is_auto=1, results=()):
    with env.factory() as db:
        run = models.ProbeRun(
            prompt="audit", created_at=NOW - timedelta(seconds=age),
            status=status, is_auto=is_auto,
        )
        db.add(run)
        db.flush()
        run_id = run.id
        for item in results:
            values = {
                "model_id": MODEL_ID, "model_name": MODEL_NAME,
                "timestamp": NOW - timedelta(seconds=age),
                "prompt": "audit", "status": "success", "category": "chat-short",
            }
            values.update(item)
            db.add(models.ProbeResult(run_id=run_id, **values))
        db.commit()
        return run_id


def utc(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.utcoffset() == timedelta(0), "API timestamps must include UTC"
    return parsed


def test_status_without_auto_runs_does_not_claim_monitoring_is_running(env):
    seed(env, status="running", is_auto=0)
    data = env.client.get("/api/auto-probe/status").json()
    assert data["is_running"] is False
    assert data["current_cycle_running"] is False
    assert data["cycle_state"] == "never_run"
    assert data["last_run_time"] is None
    assert data["last_completed_time"] is None
    assert data["next_run_time"] is None


@pytest.mark.parametrize(("status", "age", "state", "running"), [
    ("running", 60, "running", True),
    ("running", 899, "running", True),
    ("running", 900, "overdue", False),
    ("completed", 60, "completed", False),
    ("completed", 601, "overdue", False),
    ("failed", 60, "failed", False),
])
def test_status_uses_persisted_state_with_bounded_running_expiry(
    env, status, age, state, running
):
    run_id = seed(env, age=age, status=status)
    data = env.client.get("/api/auto-probe/status").json()
    assert data.get("cycle_state") == state
    assert data["current_cycle_running"] is running
    assert data["is_running"] is (state in {"running", "completed"})
    assert data["last_run_id"] == run_id
    assert data["last_run_status"] == status
    assert utc(data["last_run_time"]) == NOW - timedelta(seconds=age)


def test_completed_timestamp_does_not_advance_when_new_cycle_starts(env):
    completed_id = seed(env, age=240, results=[
        {"timestamp": NOW - timedelta(seconds=180)},
        {"model_id": "us.anthropic.audit", "model_name": "Bedrock Audit (US)",
         "timestamp": NOW - timedelta(seconds=120)},
    ])
    current_id = seed(env, age=10, status="running")
    data = env.client.get("/api/auto-probe/status").json()
    assert data.get("last_completed_run_id") == completed_id
    assert data["last_run_id"] == current_id
    assert utc(data["last_completed_time"]) == NOW - timedelta(seconds=120)
    assert utc(data["last_run_time"]) == NOW - timedelta(seconds=10)


def test_completed_run_without_results_does_not_invent_completion_time(env):
    seed(env, age=10)
    data = env.client.get("/api/auto-probe/status").json()
    assert "last_completed_time" in data
    assert data["last_completed_time"] is None


def test_status_detects_active_run_even_when_newer_run_has_completed(env):
    seed(env, age=240, status="running")
    seed(env, age=60)
    data = env.client.get("/api/auto-probe/status").json()
    assert data["current_cycle_running"] is True
    assert data["cycle_state"] == "running"


def test_status_reports_visible_registry_size_and_category_cadence(env):
    data = env.client.get("/api/auto-probe/status").json()
    assert data.get("expected_model_count") == 2
    assert data["interval_seconds"] == 300
    assert data["category_count"] == 6
    assert data["category_interval_seconds"] == 1800
    assert data["overdue_after_seconds"] == 600
    assert data["running_timeout_seconds"] == 900


def test_latest_and_trend_timestamps_include_utc(env):
    seed(env, results=[{}])
    latest = env.client.get("/api/auto-probe/latest").json()
    trend = env.client.get("/api/auto-probe/trend").json()
    assert utc(latest[0]["timestamp"]) == NOW - timedelta(seconds=60)
    assert utc(trend[0]["timestamp"]) == NOW - timedelta(seconds=60)


def test_trend_window_uses_observation_time_not_cycle_start(env):
    seed(env, age=360, results=[{"timestamp": NOW - timedelta(seconds=240)}])
    rows = env.client.get("/api/auto-probe/trend", params={"hours": 1 / 12}).json()
    assert len(rows) == 1
    assert utc(rows[0]["timestamp"]) == NOW - timedelta(seconds=240)


@pytest.mark.parametrize("failure_status", ["error", "overloaded"])
def test_hourly_trend_excludes_numeric_metrics_from_failed_probes(env, failure_status):
    seed(env, age=3600, results=[{
        "ttft_ms": 100.0, "total_latency_ms": 1000.0, "tps": 40.0,
    }])
    seed(env, age=3300, results=[{
        "status": failure_status, "ttft_ms": 900.0,
        "total_latency_ms": 60000.0, "tps": 1.0,
    }])
    hourly = env.client.get("/api/auto-probe/trend?hours=72").json()
    assert len(hourly) == 1
    assert hourly[0]["status"] == "success"
    for metric, expected in [("ttft_ms", 100.0), ("total_latency_ms", 1000.0), ("tps", 40.0)]:
        assert hourly[0][metric] == expected
        assert hourly[0][f"{metric}_min"] == expected
        assert hourly[0][f"{metric}_max"] == expected
    # The raw response contract retains failure metrics for consumers that need
    # elapsed failure time; charts use the existing status field to show gaps.
    raw = env.client.get("/api/auto-probe/trend?hours=24").json()
    assert raw[1]["status"] == failure_status
    assert raw[1]["total_latency_ms"] == 60000.0


def test_hourly_trend_with_only_failed_probes_has_null_metrics(env):
    seed(env, age=3600, results=[{
        "status": "error", "total_latency_ms": 60000.0,
    }])
    hourly = env.client.get("/api/auto-probe/trend?hours=72").json()
    assert len(hourly) == 1
    assert hourly[0]["status"] == "error"
    assert hourly[0]["total_latency_ms"] is None
    assert hourly[0]["total_latency_ms_min"] is None
    assert hourly[0]["total_latency_ms_max"] is None


def test_anomalies_only_count_auto_observations_in_selected_category(env):
    seed(env, results=[
        {"category": "reasoning", "status": "error", "error_message": "auto error"},
        {"category": "chat-short", "status": "error", "error_message": "other workload"},
        {"category": "reasoning", "model_name": "OpenAI Audit (1P)",
         "status": "error", "error_message": "hidden"},
    ])
    seed(env, is_auto=0, results=[
        {"category": "reasoning", "status": "error", "error_message": "manual error"},
    ])
    seed(env, age=13 * 3600, results=[
        {"category": "reasoning", "status": "error", "error_message": "old error"},
    ])
    # Already-observed failures remain useful while their auto run is active.
    seed(env, status="running", results=[{"category": "reasoning"}])
    data = env.client.get("/api/auto-probe/anomalies", params={
        "hours": 12, "category": "reasoning",
    }).json()
    assert data["total_probes"] == 2
    assert data["total_failures"] == 1
    assert data["category"] == "reasoning"
    assert data["models"][0]["last_error"] == "auto error"
    assert utc(data["models"][0]["last_at"]) == NOW - timedelta(seconds=60)


def test_empty_anomaly_scope_returns_zero_observations(env):
    seed(env, results=[{}])
    data = env.client.get("/api/auto-probe/anomalies?category=reasoning").json()
    assert data["total_probes"] == 0
    assert data["total_failures"] == 0
    assert data["models"] == []
    assert data["category"] == "reasoning"


def test_trigger_requires_authentication_before_reserving_a_run(env):
    response = env.client.post("/api/auto-probe/trigger")
    assert response.status_code == 401
    with env.factory() as db:
        assert db.query(models.ProbeRun).count() == 0


def test_trigger_rejects_unapproved_user(env):
    response = env.client.post("/api/auto-probe/trigger", headers={
        "Authorization": f"Bearer {auth.create_access_token('pending')}",
    })
    assert response.status_code == 403
    with env.factory() as db:
        assert db.query(models.ProbeRun).count() == 0


def test_trigger_reserves_db_run_before_responding_and_rejects_second_request(env):
    accepted = env.client.post("/api/auto-probe/trigger", headers=env.headers)
    assert accepted.status_code == 202
    run_id = accepted.json()["run_id"]
    assert accepted.json()["triggered"] is True
    with env.factory() as db:
        run = db.get(models.ProbeRun, run_id)
        assert run.status == "running" and run.is_auto == 1
    status = env.client.get("/api/auto-probe/status").json()
    assert status["current_cycle_running"] is True
    rejected = env.client.post("/api/auto-probe/trigger", headers=env.headers)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "cycle_running"
    assert rejected.json()["detail"]["run_id"] == run_id
    with env.factory() as db:
        assert db.query(models.ProbeRun).count() == 1


def test_trigger_rejects_running_scheduled_cycle_from_db(env):
    run_id = seed(env, status="running")
    response = env.client.post("/api/auto-probe/trigger", headers=env.headers)
    assert response.status_code == 409
    assert response.json()["detail"]["run_id"] == run_id


def test_expired_running_row_does_not_permanently_block_trigger(env):
    old_id = seed(env, age=901, status="running")
    response = env.client.post("/api/auto-probe/trigger", headers=env.headers)
    assert response.status_code == 202
    assert response.json()["run_id"] != old_id


def test_concurrent_trigger_admission_creates_only_one_run(env):
    barrier = threading.Barrier(2)

    def trigger():
        barrier.wait(timeout=3)
        return env.client.post("/api/auto-probe/trigger", headers=env.headers).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: trigger(), range(2)))
    assert sorted(responses) == [202, 409]
    with env.factory() as db:
        assert db.query(models.ProbeRun).count() == 1


def test_thread_start_failure_is_reported_and_releases_reservation(env, monkeypatch):
    class BrokenThread:
        def __init__(self, **kwargs):
            pass

        def start(self):
            raise RuntimeError("test thread start failure")

    monkeypatch.setattr(worker, "threading", SimpleNamespace(Thread=BrokenThread))
    response = env.client.post("/api/auto-probe/trigger", headers=env.headers)
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "trigger_failed"
    with env.factory() as db:
        assert db.query(models.ProbeRun).one().status == "failed"
    assert env.client.get("/api/auto-probe/status").json()["current_cycle_running"] is False


def test_scheduled_cycle_honors_an_existing_manual_reservation(env):
    accepted = env.client.post("/api/auto-probe/trigger", headers=env.headers)
    assert accepted.status_code == 202
    assert worker.run_cycle() == accepted.json()["run_id"]
    with env.factory() as db:
        assert db.query(models.ProbeRun).count() == 1


def test_reserved_cycle_failure_is_persisted_and_running_flag_is_reset(env):
    accepted = env.client.post("/api/auto-probe/trigger", headers=env.headers)
    assert accepted.status_code == 202
    # The fixture's provider boundary raises immediately; it cannot call AWS.
    thread = env.deferred[0]
    thread.target(*thread.args, **thread.kwargs)
    with env.factory() as db:
        assert db.get(models.ProbeRun, accepted.json()["run_id"]).status == "failed"
    assert worker.auto_prober.current_cycle_running is False


def test_worker_exception_does_not_publish_an_empty_completed_cycle(env, monkeypatch):
    monkeypatch.setattr(worker, "AVAILABLE_MODELS", {MODEL_ID: MODEL_NAME})
    monkeypatch.setattr(worker, "_get_bedrock_client", lambda region: object())

    def failed_probe(*args, **kwargs):
        raise RuntimeError("simulated result persistence failure")

    monkeypatch.setattr(worker, "_probe_single_model", failed_probe)
    with pytest.raises(RuntimeError):
        worker.run_cycle()
    with env.factory() as db:
        assert db.query(models.ProbeRun).one().status == "failed"
        assert db.query(models.ProbeResult).count() == 0
    assert worker.auto_prober.current_cycle_running is False


def test_accepted_cycle_completes_the_reserved_run_and_publishes_results(env, monkeypatch):
    monkeypatch.setattr(worker, "AVAILABLE_MODELS", {MODEL_ID: MODEL_NAME})
    monkeypatch.setattr(worker, "_get_bedrock_client", lambda region: object())

    def observed_probe(client, model_id, model_name, prompt, temperature,
                       max_tokens, iteration, event_queue, run_id, db, category):
        db.add(models.ProbeResult(
            run_id=run_id, model_id=model_id, model_name=model_name,
            prompt=prompt, timestamp=NOW, status="success", category=category,
        ))
        db.commit()

    monkeypatch.setattr(worker, "_probe_single_model", observed_probe)
    accepted = env.client.post("/api/auto-probe/trigger", headers=env.headers)
    assert accepted.status_code == 202
    run_id = accepted.json()["run_id"]
    thread = env.deferred[0]
    thread.target(*thread.args, **thread.kwargs)
    with env.factory() as db:
        assert db.query(models.ProbeRun).one().id == run_id
        assert db.get(models.ProbeRun, run_id).status == "completed"
    latest = env.client.get("/api/auto-probe/latest").json()
    assert len(latest) == 1
    assert latest[0]["run_id"] == run_id
    assert latest[0]["category"] == "chat-short"
    status = env.client.get("/api/auto-probe/status").json()
    assert status["last_completed_run_id"] == run_id
    assert utc(status["last_completed_time"]) == NOW
    assert status["current_cycle_running"] is False
