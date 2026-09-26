"""PricingSync one-shot runner (v2.30.0, ADR-030): order, exit codes, advisory lock 917350004, os._exit."""

import os
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pricing_sync_runner as runner
from database import Base
from models import PriceSyncRun

BACKEND = Path(__file__).resolve().parents[1]
T0 = datetime(2026, 9, 26, 15, 0, tzinfo=timezone.utc)
LOCK = {"key": 917350004}


@pytest.fixture()
def wired(monkeypatch):
    """Every collaborator faked on SQLite; `calls` records the order, `status` is how the fake run ends."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    state = SimpleNamespace(calls=[], status="completed", seed_active=None, sync_active=None, engine=engine)
    models = {"global.anthropic.claude-opus-5-5": "Bedrock Claude Opus 5.5 (Global)"}

    def discover():
        state.calls.append("discover_cp")
        models["anthropic:claude-opus-5-5"] = "Anthropic Claude Opus 5.5 (US)"

    def register_openai():
        state.calls.append("register_openai")
        models["openai:us-east-1:openai.gpt-6-sol"] = "OpenAI GPT 6 Sol (us-east-1)"
        models["openai:1p:gpt-5.4"] = "OpenAI GPT 5.4 (1P)"  # hidden by the default HIDDEN_MODEL_PATTERNS

    def ensure_seed(bind, active):
        state.calls.append("ensure_seed")
        state.seed_active = dict(active)
        return 3

    def run_sync(session_factory, active, fetchers):
        state.calls.append("run_sync")
        assert session_factory is Session and fetchers == "fetchers"
        state.sync_active = dict(active)
        with session_factory() as db:
            run = PriceSyncRun(started_at=T0, finished_at=T0, status=state.status, changes=0, pending=0,
                               summary={"sources": {}, "channels": {m: "unchanged" for m in active}, "errors": []})
            db.add(run)
            db.commit()
            return run.id

    for name, value in {
        "engine": engine, "SessionLocal": Session, "AVAILABLE_MODELS": models,
        "create_tables": lambda: state.calls.append("create_tables"), "_discover_anthropic_models": discover,
        "_register_openai_models": register_openai, "ensure_seed": ensure_seed, "run_sync": run_sync,
        "default_fetchers": lambda: "fetchers",
    }.items():
        monkeypatch.setattr(runner, name, value)
    monkeypatch.delenv("HIDDEN_MODEL_PATTERNS", raising=False)
    yield state
    engine.dispose()


def test_registration_runs_before_ensure_seed_before_run_sync(wired):
    assert runner.main(["--once"]) == 0
    assert wired.calls == ["create_tables", "discover_cp", "register_openai", "ensure_seed", "run_sync"]
    assert set(wired.seed_active) == {"global.anthropic.claude-opus-5-5", "anthropic:claude-opus-5-5",
                                      "openai:us-east-1:openai.gpt-6-sol"}  # registered ids in, (1P) hidden
    assert wired.sync_active == wired.seed_active and wired.seed_active["anthropic:claude-opus-5-5"].channel == "cp"


@pytest.mark.parametrize(("status", "code"), [("completed", 0), ("partial", 0), ("failed", 1)])
def test_exit_code_follows_the_run_status(wired, status, code):
    wired.status = status
    assert runner.main(["--once"]) == code


def test_create_tables_failure_exits_one_before_seed_or_sync(wired, monkeypatch):
    def broken():
        wired.calls.append("create_tables")
        raise RuntimeError("could not connect to the database")

    monkeypatch.setattr(runner, "create_tables", broken)
    assert runner.main(["--once"]) == 1
    assert "ensure_seed" not in wired.calls and "run_sync" not in wired.calls
    assert wired.calls == ["create_tables"]  # not even model registration runs


def test_a_failing_registration_is_not_fatal(wired, monkeypatch):
    def broken():
        wired.calls.append("discover_cp")
        raise RuntimeError("CP /v1/models 500")

    monkeypatch.setattr(runner, "_discover_anthropic_models", broken)
    assert runner.main(["--once"]) == 0
    assert wired.calls == ["create_tables", "discover_cp", "register_openai", "ensure_seed", "run_sync"]
    assert "anthropic:claude-opus-5-5" not in wired.sync_active


def _raise(message):
    def fail(*_args):
        raise RuntimeError(message)
    return fail


def test_no_sync_when_ensure_seed_fails_and_a_raising_sync_exits_one(wired, monkeypatch):
    monkeypatch.setattr(runner, "ensure_seed", _raise("seed insert failed"))
    assert runner.main(["--once"]) == 1 and "run_sync" not in wired.calls
    monkeypatch.setattr(runner, "ensure_seed", lambda bind, active: 0)
    monkeypatch.setattr(runner, "run_sync", _raise("database went away"))
    assert runner.main(["--once"]) == 1


def test_once_is_required(wired):
    with pytest.raises(SystemExit):
        runner.main([])
    assert wired.calls == []


class _FakePgConnection:
    def __init__(self, lock_free):
        self.lock_free, self.statements, self.closed = lock_free, [], False

    def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        return SimpleNamespace(scalar=lambda: self.lock_free if "pg_try_advisory_lock" in str(statement) else True)

    def commit(self):
        pass

    def invalidate(self):
        pass

    def close(self):
        self.closed = True


@pytest.mark.parametrize(("lock_free", "code", "statements"), [
    (True, 0, [("SELECT pg_try_advisory_lock(:key)", LOCK), ("SELECT pg_advisory_unlock(:key)", LOCK)]),
    (False, 1, [("SELECT pg_try_advisory_lock(:key)", LOCK)]),               # busy: exit 1, nothing to release
])
def test_postgresql_runs_under_the_advisory_lock(wired, monkeypatch, lock_free, code, statements):
    conn = _FakePgConnection(lock_free)
    monkeypatch.setattr(runner, "engine", SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: conn))
    assert runner.main(["--once"]) == code
    assert ("run_sync" in wired.calls) is lock_free
    assert conn.statements == statements and conn.closed


def test_sqlite_skips_the_lock(wired):
    assert wired.engine.dialect.name == "sqlite"
    assert runner.main(["--once"]) == 0 and "run_sync" in wired.calls


def test_module_entrypoint_hard_exits_with_the_run_status(tmp_path):
    """`python -m pricing_sync_runner --once` on a SQLite file DB: partial run -> exit 0, logs flushed, and a
    live non-daemon thread does not keep the process alive (os._exit, as in auto_prober_runner)."""
    script = textwrap.dedent("""
        import runpy, sys, threading
        from datetime import datetime, timezone
        import prober, pricing_seed, pricing_sync

        prober._discover_anthropic_models = lambda: None
        prober._register_openai_models = lambda: None
        pricing_seed.ensure_seed = lambda bind, active: 0
        pricing_sync.default_fetchers = lambda: None

        def fake_run_sync(session_factory, active, fetchers):
            from models import PriceSyncRun
            threading.Thread(target=threading.Event().wait, daemon=False).start()  # never finishes
            with session_factory() as db:
                run = PriceSyncRun(started_at=datetime.now(timezone.utc), status="partial", changes=0, pending=0,
                                   summary={"sources": {}, "channels": {}, "errors": []})
                db.add(run)
                db.commit()
                return run.id

        pricing_sync.run_sync = fake_run_sync
        sys.argv = ["pricing_sync_runner", "--once"]
        runpy.run_module("pricing_sync_runner", run_name="__main__")
        print("UNREACHABLE: _finish must not return")
    """)
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{tmp_path / 'sync.db'}")
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, "-c", script], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert "UNREACHABLE" not in proc.stdout
    assert "pricing_sync_runner: run_id=1 status=partial" in proc.stderr
    assert time.perf_counter() - t0 < 30


def test_hidden_model_patterns_are_applied_to_the_active_set(wired, monkeypatch):
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P),(us-east-1)")
    assert runner.main(["--once"]) == 0
    assert "openai:us-east-1:openai.gpt-6-sol" not in wired.seed_active
    assert "openai:us-east-1:openai.gpt-6-sol" not in wired.sync_active
