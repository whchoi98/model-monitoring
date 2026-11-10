"""model_explorer.runner — fake executor + in-memory SQLite, no child process, no provider (v2.40.0, ADR-035)."""

import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from model_explorer import runner
from model_explorer.examples import code_examples
from model_explorer.execute import Outcome
from models import ExplorerResult, ExplorerRun

MODELS = {
    "global.anthropic.claude-opus-5": "Bedrock Claude Opus 5 (Global)",           # 3 examples
    "us.amazon.nova-2-lite-v1:0": "Bedrock Nova 2.0 Lite (US)",                    # 1
    "anthropic:claude-sonnet-5-5": "Anthropic Claude Sonnet 5.5 (US)",             # 1
    "openai:us-east-1:openai.gpt-6-sol": "OpenAI GPT 6 Sol (us-east-1)",           # 1
    "openai:1p:gpt-5.5": "OpenAI GPT 5.5 (1P)",                                    # hidden by default
    "global.anthropic.claude-haiku-4-5-20251001-v1:0": "Bedrock Claude Haiku 4.5 (Global)",  # hidden (v2.39.0)
}
T0 = datetime(2026, 11, 5, 18, 0, tzinfo=timezone.utc)


@pytest.fixture()
def Session(monkeypatch):
    monkeypatch.delenv("HIDDEN_MODEL_PATTERNS", raising=False)
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, autoflush=False)
    engine.dispose()


def _passing(code):
    return Outcome("passed", 12.5, 1, "Hello!", None)


def _rows(Session, run_id):
    with Session() as db:
        rows = db.query(ExplorerResult).filter(ExplorerResult.run_id == run_id).order_by(ExplorerResult.id).all()
        db.expunge_all()
        return rows


def _run(Session, run_id):
    with Session() as db:
        run = db.get(ExplorerRun, run_id)
        db.expunge(run)
        return run


def test_jobs_are_every_visible_model_times_its_examples():
    jobs = runner.build_jobs(runner.visible_models(MODELS))
    assert [(j["model_id"], j["api_id"]) for j in jobs] == [
        ("global.anthropic.claude-opus-5", "converse"), ("global.anthropic.claude-opus-5", "invoke_model"),
        ("global.anthropic.claude-opus-5", "messages"), ("us.amazon.nova-2-lite-v1:0", "converse"),
        ("anthropic:claude-sonnet-5-5", "messages"), ("openai:us-east-1:openai.gpt-6-sol", "responses"),
    ]
    first = code_examples("global.anthropic.claude-opus-5")[0]
    assert jobs[0]["code"] == first["code"]["en"] and jobs[0]["code_sha"] == first["code_sha"]


def test_the_production_catalog_makes_85_jobs():
    from tests.pricing_catalog import ACTIVE_MODELS

    assert len(runner.build_jobs(runner.visible_models(ACTIVE_MODELS))) == 85  # v2.42.0: − Fable 5 (7 examples)


def test_a_run_saves_one_row_per_example_with_totals(Session):
    calls = []

    def fake(code):
        calls.append(code)
        return Outcome("failed", 30.0, 2, None, "KeyError: 'text'\ntail") if "invoke_model" in code else _passing(code)

    run_id = runner.run_explorer(session_factory=Session, execute_fn=fake, models=MODELS, now=lambda: T0)
    run = _run(Session, run_id)
    assert (run.status, run.totals) == ("completed", {"passed": 5, "failed": 1, "skipped": 0})
    rows = _rows(Session, run_id)
    assert len(rows) == len(calls) == 6
    failed = next(r for r in rows if r.api_id == "invoke_model")
    assert (failed.status, failed.attempts, failed.error_message) == ("failed", 2, "KeyError: 'text'\ntail")
    assert all(r.model_name == MODELS[r.model_id] for r in rows)
    assert {r.code_sha for r in rows} == {
        ex["code_sha"] for mid in list(MODELS)[:4] for ex in code_examples(mid)}


def test_hidden_models_are_not_run(Session):
    run_id = runner.run_explorer(session_factory=Session, execute_fn=_passing, models=MODELS)
    assert {r.model_id for r in _rows(Session, run_id)} == set(list(MODELS)[:4])


def test_the_running_row_is_committed_before_the_first_example(Session, monkeypatch):
    monkeypatch.setattr(runner, "MAX_WORKERS", 1)  # one worker: the shared in-memory SQLite connection is not thread-safe
    seen = []

    def fake(code):
        with Session() as db:
            seen.append([(r.status, r.finished_at) for r in db.query(ExplorerRun).all()])
        return _passing(code)

    runner.run_explorer(session_factory=Session, execute_fn=fake, models=MODELS)
    assert seen[0] == [("running", None)]


def test_jobs_past_the_run_deadline_are_skipped(Session):
    def slow(code):
        time.sleep(0.05)
        return _passing(code)

    run_id = runner.run_explorer(session_factory=Session, execute_fn=slow, models=MODELS, deadline_s=0.0)
    rows = _rows(Session, run_id)
    assert {r.status for r in rows} == {"skipped"}
    assert {r.error_message for r in rows} == {runner.RUN_DEADLINE_REASON}
    assert _run(Session, run_id).totals == {"passed": 0, "failed": 0, "skipped": 6}


def test_an_executor_exception_is_a_failed_row_not_a_failed_run(Session):
    def boom(code):
        raise RuntimeError("worker died")

    run_id = runner.run_explorer(session_factory=Session, execute_fn=boom, models=MODELS)
    assert _run(Session, run_id).status == "completed"
    assert {r.error_message for r in _rows(Session, run_id)} == {"executor: RuntimeError: worker died"}


def test_an_internal_error_marks_the_run_failed_and_reraises(Session, monkeypatch):
    monkeypatch.setattr(runner, "_totals", lambda results: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(RuntimeError, match="db down"):
        runner.run_explorer(session_factory=Session, execute_fn=_passing, models=MODELS)
    with Session() as db:
        (run,) = db.query(ExplorerRun).all()
        assert (run.status, run.error_message) == ("failed", "db down") and run.finished_at is not None


def test_only_the_latest_60_runs_are_kept(Session):
    with Session() as db:
        for i in range(61):
            db.add(ExplorerRun(status="completed", started_at=T0 - timedelta(days=61 - i)))
        db.commit()
        old_id = db.query(ExplorerRun.id).order_by(ExplorerRun.id).first()[0]
        db.add(ExplorerResult(run_id=old_id, model_id="m", model_name="m", api_id="converse", status="passed",
                              attempts=1, code_sha="x"))
        db.commit()
    runner.run_explorer(session_factory=Session, execute_fn=_passing, models=MODELS)
    with Session() as db:
        assert db.query(ExplorerRun).count() == runner.KEEP_RUNS
        assert db.query(ExplorerRun).filter(ExplorerRun.id == old_id).first() is None
        assert db.query(ExplorerResult).filter(ExplorerResult.run_id == old_id).count() == 0


def test_a_prune_failure_never_overwrites_the_completed_run(Session, monkeypatch):
    monkeypatch.setattr(runner, "_prune", lambda factory: (_ for _ in ()).throw(RuntimeError("prune")))
    run_id = runner.run_explorer(session_factory=Session, execute_fn=_passing, models=MODELS)
    assert _run(Session, run_id).status == "completed"


def test_examples_run_four_at_a_time(Session):
    active, peak, lock = [0], [0], threading.Lock()

    def fake(code):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return _passing(code)

    runner.run_explorer(session_factory=Session, execute_fn=fake, models=MODELS)
    assert peak[0] == runner.MAX_WORKERS


def test_the_trigger_style_run_uses_two_workers(Session):
    active, peak, lock = [0], [0], threading.Lock()

    def fake(code):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        time.sleep(0.05)
        with lock:
            active[0] -= 1
        return _passing(code)

    runner.run_explorer(session_factory=Session, execute_fn=fake, models=MODELS, max_workers=2)
    assert peak[0] == 2


def test_sweep_wait_covers_the_deadline_and_one_retried_example(monkeypatch):
    monkeypatch.setenv("EXPLORER_CALL_TIMEOUT_S", "90")
    assert runner.sweep_wait_s(1200.0) == 1410.0


def _stuck_fn(release):
    def fn(code):
        if code == "stuck":
            release.wait(10)
        return _passing(code)
    return fn


_STUCK_JOBS = [{"code": "stuck"}, {"code": "ok-1"}, {"code": "ok-2"}]


def test_a_stuck_example_never_holds_the_sweep():
    release = threading.Event()
    try:
        t0 = time.monotonic()
        results = runner._sweep(list(_STUCK_JOBS), _stuck_fn(release), 60.0, max_workers=1, wait_s=1.0)
        elapsed = time.monotonic() - t0
    finally:
        release.set()
    assert elapsed < 3.0
    assert len(results) == 3
    by_code = {job["code"]: (o.status, o.error_message) for job, o in results}
    assert by_code["stuck"] == ("failed", "시간 초과 1초")
    assert by_code["ok-1"] == ("skipped", runner.RUN_DEADLINE_REASON)
    assert by_code["ok-2"] == ("skipped", runner.RUN_DEADLINE_REASON)


def test_finished_examples_keep_their_result_when_another_is_stuck():
    release = threading.Event()
    try:
        results = runner._sweep(list(_STUCK_JOBS), _stuck_fn(release), 60.0, max_workers=2, wait_s=1.0)
    finally:
        release.set()
    by_code = {job["code"]: (o.status, o.error_message) for job, o in results}
    assert by_code["stuck"] == ("failed", "시간 초과 1초")
    assert by_code["ok-1"][0] == "passed" and by_code["ok-2"][0] == "passed"


def test_smoke_runs_without_the_database():
    rows = runner.smoke(execute_fn=_passing, models=MODELS)
    assert [(r["model_id"], r["api_id"], r["status"]) for r in rows][:2] == [
        ("anthropic:claude-sonnet-5-5", "messages", "passed"), ("global.anthropic.claude-opus-5", "converse", "passed")]
    assert len(rows) == 6


# ── CLI (explorer_runner.py) ─────────────────────────────────────────────────

import json  # noqa: E402

import explorer_runner  # noqa: E402


def test_cli_needs_once_or_smoke():
    with pytest.raises(SystemExit):
        explorer_runner.main([])


def test_cli_smoke_prints_json_and_exits_1_on_a_failed_example(monkeypatch, capsys):
    row = {"model_id": "m", "model_name": "M", "api_id": "converse", "status": "failed", "latency_ms": 1.0,
           "attempts": 2, "output_excerpt": None, "error_message": "KeyError: 'x'\ntail"}
    monkeypatch.setattr(explorer_runner, "_register_models", lambda: None)
    monkeypatch.setattr(runner, "smoke", lambda model_ids: [row])
    assert explorer_runner.main(["--smoke", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == [row]


def test_cli_once_registers_models_creates_tables_then_runs(monkeypatch):
    import database

    calls = []
    monkeypatch.setattr(explorer_runner, "_register_models", lambda: calls.append("register"))
    monkeypatch.setattr(database, "create_tables", lambda: calls.append("tables"))
    monkeypatch.setattr(runner, "run_explorer", lambda model_ids: calls.append(("run", model_ids)) or 7)
    assert explorer_runner.main(["--once", "--models", "a,b"]) == 0
    assert calls == ["register", "tables", ("run", ["a", "b"])]


def test_cli_once_exits_1_when_the_run_fails(monkeypatch):
    import database

    monkeypatch.setattr(explorer_runner, "_register_models", lambda: None)
    monkeypatch.setattr(database, "create_tables", lambda: None)
    monkeypatch.setattr(runner, "run_explorer", lambda model_ids: (_ for _ in ()).throw(RuntimeError("x")))
    assert explorer_runner.main(["--once"]) == 1


def test_finish_ends_with_os_exit(monkeypatch):
    codes = []
    monkeypatch.setattr(explorer_runner.logging, "shutdown", lambda: None)
    explorer_runner._finish(3, _exit=codes.append)
    assert codes == [3]
