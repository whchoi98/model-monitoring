"""/api/auto-probe/latest per model, cadence fields in /status, chatbot latest tool (v2.29.0).

Claude Platform on AWS channels are probed every other cycle and rotate categories on their own, so the
rows of the single latest run no longer cover every model. /latest returns each model's latest row from
completed automatic runs within a bounded window derived from that model's own cadence.

All records live in SQLite memory; no provider is called.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auto_prober as worker
import models
import probe_cadence
from agent import tools
from database import get_db
from routers import auto_probe

ANCHOR = datetime(2026, 9, 24, 3, 0, tzinfo=timezone.utc)
BEDROCK = ("global.anthropic.claude-sonnet-5", "Bedrock Claude Sonnet 5 (Global)")
NOVA = ("us.amazon.nova-2-lite-v1:0", "Bedrock Nova 2.0 Lite (US)")
CP = ("anthropic:claude-sonnet-5", "Anthropic Claude Sonnet 5 (US)")
HIDDEN = ("openai:1p:gpt-5.4", "OpenAI GPT 5.4 (1P)")


@pytest.fixture()
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(probe_cadence, "ANTHROPIC_CP_PROBE_INTERVAL_S", 600)
    monkeypatch.setattr(worker, "AVAILABLE_MODELS", {mid: name for mid, name in (BEDROCK, NOVA, CP, HIDDEN)})
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")

    app = FastAPI()
    app.include_router(auto_probe.router)

    def db_override():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    with TestClient(app) as client:
        yield engine, factory, client
    engine.dispose()


def run(factory, age, rows=(), *, status="completed", is_auto=1):
    """A run started `age` seconds before ANCHOR; rows = (model, category, row_age)."""
    with factory() as db:
        probe_run = models.ProbeRun(prompt="p", created_at=ANCHOR - timedelta(seconds=age),
                                    status=status, is_auto=is_auto)
        db.add(probe_run)
        db.flush()
        for (model_id, model_name), category, row_age in rows:
            db.add(models.ProbeResult(
                run_id=probe_run.id, model_id=model_id, model_name=model_name, prompt="p",
                timestamp=ANCHOR - timedelta(seconds=row_age), status="success", category=category,
                ttft_ms=100.0,
            ))
        db.commit()
        return probe_run.id


def latest(client, **params):
    return [(r["model_id"], r["run_id"], r["category"]) for r in client.get("/api/auto-probe/latest", params=params).json()]


def test_cp_rows_from_the_previous_run_fill_a_cycle_that_skipped_cp(env):
    _, factory, client = env
    previous = run(factory, 300, [(BEDROCK, "chat-short", 290), (CP, "summarize", 210), (NOVA, "chat-short", 280)])
    newest = run(factory, 0, [(BEDROCK, "reasoning", -10), (NOVA, "reasoning", -20)])

    assert latest(client) == [
        (CP[0], previous, "summarize"),      # "Anthropic ..." sorts first by model_name
        (BEDROCK[0], newest, "reasoning"),
        (NOVA[0], newest, "reasoning"),
    ]


def test_lookback_is_three_of_each_models_own_intervals(env):
    _, factory, client = env
    run(factory, 1900, [(CP, "chat-short", 1890)])        # older than 3 x 600 s
    run(factory, 1000, [(BEDROCK, "chat-short", 990)])   # older than 3 x 300 s
    run(factory, 850, [(NOVA, "chat-short", 840)])       # within 3 x 300 s
    run(factory, 0, [])

    assert [m for m, _, _ in latest(client)] == [NOVA[0]]


def test_only_completed_automatic_runs_are_published(env):
    _, factory, client = env
    completed = run(factory, 300, [(BEDROCK, "chat-short", 290), (CP, "chat-short", 250)])
    run(factory, 200, [(CP, "reasoning", 190)], status="failed")
    run(factory, 100, [(BEDROCK, "code-gen", 90)], is_auto=0)
    run(factory, 10, [(BEDROCK, "reasoning", 5)], status="running")

    assert latest(client) == [(CP[0], completed, "chat-short"), (BEDROCK[0], completed, "chat-short")]


def test_hidden_channels_stay_hidden(env):
    _, factory, client = env
    run(factory, 0, [(BEDROCK, "chat-short", -5), (HIDDEN, "chat-short", -6)])
    assert [m for m, _, _ in latest(client)] == [BEDROCK[0]]


def test_no_completed_run_returns_empty(env):
    _, factory, client = env
    run(factory, 10, [(BEDROCK, "chat-short", 5)], status="running")
    assert latest(client) == []


def test_category_returns_each_models_latest_row_in_that_category(env):
    _, factory, client = env
    run(factory, 3700, [(BEDROCK, "code-gen", 3690)])     # beyond 2 x 30 min for a 5-minute channel
    old_cp = run(factory, 7000, [(CP, "code-gen", 6900)])  # within 2 x 60 min for CP
    rotation = run(factory, 1800, [(BEDROCK, "code-gen", 1790), (NOVA, "code-gen", 1780)])
    nova_newer = run(factory, 1500, [(NOVA, "code-gen", 1490)])
    run(factory, 0, [(BEDROCK, "reasoning", -5), (NOVA, "reasoning", -6)])

    assert latest(client, category="code-gen") == [
        (CP[0], old_cp, "code-gen"),
        (BEDROCK[0], rotation, "code-gen"),
        (NOVA[0], nova_newer, "code-gen"),
    ]


def test_category_window_for_cp_is_bounded(env):
    _, factory, client = env
    run(factory, 7300, [(CP, "code-gen", 7250)])  # beyond 2 x 6 x 600 s
    run(factory, 0, [(BEDROCK, "code-gen", -5)])
    assert [m for m, _, _ in latest(client, category="code-gen")] == [BEDROCK[0]]


def test_latest_is_three_bounded_queries(env):
    """Anchor run, one timestamp-bounded aggregate, one primary-key fetch — no per-model or full scans."""
    engine, factory, client = env
    run(factory, 300, [(BEDROCK, "chat-short", 290), (CP, "chat-short", 250)])
    run(factory, 0, [(BEDROCK, "reasoning", -5)])
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(" ".join(statement.split()))

    event.listen(engine, "before_cursor_execute", capture)
    try:
        assert len(latest(client)) == 2
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    selects = [s for s in statements if s.startswith("SELECT")]
    assert len(selects) == 3
    anchor, aggregate, fetch = selects
    assert "FROM probe_runs" in anchor and "ORDER BY probe_runs.created_at DESC" in anchor
    assert "probe_results.timestamp >=" in aggregate and "GROUP BY probe_results.model_id" in aggregate
    assert "probe_results.id IN" in fetch


def test_status_reports_channel_cadence_and_keeps_existing_fields(env):
    _, _, client = env
    data = client.get("/api/auto-probe/status").json()
    assert data["interval_seconds"] == 300
    assert data["category_interval_seconds"] == 1800
    assert data["channel_intervals"] == {"anthropic": 600}
    assert data["channel_category_intervals"] == {"anthropic": 3600}


def test_status_cadence_follows_the_configured_interval(env, monkeypatch):
    _, _, client = env
    monkeypatch.setattr(probe_cadence, "ANTHROPIC_CP_PROBE_INTERVAL_S", 900)
    data = client.get("/api/auto-probe/status").json()
    assert data["channel_intervals"] == {"anthropic": 900}
    assert data["channel_category_intervals"] == {"anthropic": 5400}


def test_chatbot_latest_tool_includes_cp_from_the_previous_run(env):
    _, factory, _ = env
    previous = run(factory, 300, [(BEDROCK, "chat-short", 290), (CP, "summarize", 210)])
    newest = run(factory, 0, [(BEDROCK, "reasoning", -10)])

    with factory() as db:
        out = tools.get_latest_results(db)
        only_cp = tools.get_latest_results(db, model_id=CP[0])
    assert out["run_id"] == newest
    assert [(r["model_id"], r["timestamp"][:19]) for r in out["results"]] == [
        (CP[0], (ANCHOR - timedelta(seconds=210)).isoformat()[:19]),
        (BEDROCK[0], (ANCHOR + timedelta(seconds=10)).isoformat()[:19]),
    ]
    assert [r["model_id"] for r in only_cp["results"]] == [CP[0]]
    assert previous != newest
