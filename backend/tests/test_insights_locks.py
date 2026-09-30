"""인사이트 요약 동안 DB 락을 쥐지 않는다 — 2026-09-30 v2.32.1 배포 뒤 확인(v2.32.2).

운영: backend 기동 네 번 중 두 번이 lifespan 마이그레이션 블록에서 5초 뒤 LockNotAvailable로 실패했다
(`ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS is_auto INTEGER DEFAULT 0`). 두 번 다 Insights 태스크가 도는 중이었다.
insights_runner.run_once는 run id와 통계를 읽은 세션을 commit이나 rollback 없이 둔 채 Bedrock 요약(KO, EN — 운영 2~7분)을
불렀고, 그동안 probe_runs, probe_results(+ 인덱스)의 ACCESS SHARE 락이 남았다. PostgreSQL의 ADD COLUMN IF NOT EXISTS는
열이 있는지 보기 전에 ACCESS EXCLUSIVE를 요청하므로, 열이 이미 있어도 그 락 뒤에서 lock_timeout(5초)까지 기다렸다.
POST /api/insights/regenerate 스레드도 run_once를 부르고, /stream-regenerate는 통계를 읽은 generator 세션으로 Bedrock
스트림 끝까지 probe_results를, 인증에서 users를 읽은 요청 세션으로 응답이 끝날 때까지 users를 쥐었다(FastAPI 0.142).

고정하는 것:
- SQLite(세션 호출 순서): 요약(Bedrock 호출) 동안 열린 세션 트랜잭션이 하나도 없다. probe_* 조회는 모두 첫 Bedrock 호출
  전에 끝나고, Insight INSERT는 마지막 Bedrock 호출 뒤에 새로 연 세션에서 한 번 한다. run_once, regenerate 스레드,
  stream-regenerate(generator 세션과 요청 세션) 세 경로다.
- PostgreSQL(TEST_PG_URL이 있을 때만): 같은 순간 pg_locks에 이 스키마의 테이블이나 인덱스 락을 쥔 다른 세션이 없고,
  lock_timeout 2초로 건 `ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS …`(와 probe_results, users)가 성공한다.
  예: docker run -d --rm --name <이름> -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=pg postgres:16 뒤
  TEST_PG_URL=postgresql://postgres:pg@127.0.0.1:55432/postgres python3.12 -m pytest tests/test_insights_locks.py
"""

import os
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import agent.bedrock
import insights_runner
import models
from auth import create_access_token
from database import get_db
from routers import insights as insights_router
from tests._read_dataset import FrozenDatetime, seed

_USER = "tester@example.com"


def _lang(system) -> str:
    return "ko" if system and "한국어" in system else "en"


def _tracked_factory(bind, sessions: list, timeline: list):
    """만든 세션을 순서대로 모으는 sessionmaker — 요약 순간에 열린 트랜잭션을 센다."""

    class Tracked(Session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            timeline.append(("session", len(sessions)))
            sessions.append(self)

    return sessionmaker(bind=bind, class_=Tracked)


def _install_fake_bedrock(monkeypatch, on_call):
    """run_once(converse_stream_collect, v2.32.1은 converse_blocking)와 stream-regenerate(converse_stream_text) 대역.

    on_call(lang)은 요약 호출 순간에 부른다 — 그 순간의 세션, 락 상태를 기록한다.
    """

    def collect(messages, *, model_id, system=None, max_tokens=2048, temperature=0.1, wall_clock_s=None, client=None):
        on_call(_lang(system))
        return SimpleNamespace(text=f"{_lang(system)} 요약", stop_reason="end_turn", input_tokens=10,
                               output_tokens=20, elapsed_s=0.01)

    def blocking(messages, *, model_id, system=None, max_tokens=2048, temperature=0.1):
        on_call(_lang(system))
        return f"{_lang(system)} 요약"

    def stream(messages, *, model_id, system=None, max_tokens=2048, temperature=0.1):
        on_call(_lang(system))
        yield "부분 1"
        yield "부분 2"

    monkeypatch.setattr(agent.bedrock, "converse_stream_collect", collect, raising=False)
    monkeypatch.setattr(agent.bedrock, "insights_client", lambda: object(), raising=False)
    monkeypatch.setattr(agent.bedrock, "converse_blocking", blocking)
    monkeypatch.setattr(agent.bedrock, "converse_stream_text", stream)


def _seed_user(factory) -> str:
    with factory() as db:
        db.add(models.User(username=_USER, password_hash="x", approved=1))
        db.commit()
    return create_access_token(_USER)


def _app(factory) -> FastAPI:
    """insights 라우터 + 실제 get_current_user(토큰 → users 조회). 요청 세션도 factory에서 나온다."""
    app = FastAPI()
    app.include_router(insights_router.router)

    def db_override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = db_override
    return app


# ───────────────────────────────────────────────────────────────────────
# SQLite — 세션 호출 순서
# ───────────────────────────────────────────────────────────────────────


@pytest.fixture()
def tracked(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    seed(sessionmaker(bind=engine))
    sessions: list = []
    timeline: list = []
    factory = _tracked_factory(engine, sessions, timeline)

    def record(conn, cursor, statement, parameters, context, executemany):
        timeline.append(("sql", statement))

    event.listen(engine, "before_cursor_execute", record)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    monkeypatch.setattr(insights_runner, "datetime", FrozenDatetime)
    monkeypatch.setattr(insights_runner, "SessionLocal", factory)
    monkeypatch.setattr(insights_router, "SessionLocal", factory)
    monkeypatch.setattr(insights_router, "_is_regenerating", False)

    def on_call(lang):
        timeline.append(("bedrock", lang, [i for i, s in enumerate(sessions) if s.in_transaction()]))

    _install_fake_bedrock(monkeypatch, on_call)
    try:
        yield SimpleNamespace(engine=engine, factory=factory, sessions=sessions, timeline=timeline)
    finally:
        event.remove(engine, "before_cursor_execute", record)
        engine.dispose()


def _positions(timeline, predicate) -> list[int]:
    return [i for i, entry in enumerate(timeline) if predicate(entry)]


def _assert_read_then_summaries_then_fresh_save(timeline, *, langs, first_session=0):
    """first_session보다 앞의 세션(예: /regenerate 요청 세션 — 응답과 함께 닫힌다)은 트랜잭션 검사에서 뺀다."""
    calls = [entry for entry in timeline if entry[0] == "bedrock"]
    assert sorted(lang for _, lang, _ in calls) == sorted(langs)
    for _, lang, open_txns in calls:
        mine = [i for i in open_txns if i >= first_session]
        assert mine == [], f"{lang} 요약 동안 열린 세션 트랜잭션: {mine}"
    bedrock_at = _positions(timeline, lambda e: e[0] == "bedrock")
    reads = _positions(timeline, lambda e: e[0] == "sql" and e[1].lstrip().upper().startswith("SELECT")
                       and ("FROM probe_results" in e[1] or "FROM probe_runs" in e[1]))
    inserts = _positions(timeline, lambda e: e[0] == "sql" and e[1].lstrip().upper().startswith("INSERT INTO INSIGHTS"))
    assert reads and max(reads) < min(bedrock_at)  # 통계 조회는 요약 전에 끝났다
    assert len(inserts) == 1 and inserts[0] > max(bedrock_at)
    # 저장한 세션은 요약 뒤에 새로 열었다 — INSERT 직전에 만든 마지막 세션
    opened = [(i, e[1]) for i, e in enumerate(timeline) if e[0] == "session"]
    assert any(max(bedrock_at) < i < inserts[0] for i, _ in opened), opened


def test_run_once_holds_no_transaction_while_summarizing_and_saves_in_a_fresh_session(tracked):
    insight_id = insights_runner.run_once("6h")
    assert insight_id > 0
    _assert_read_then_summaries_then_fresh_save(tracked.timeline, langs=["ko", "en"])
    assert not any(s.in_transaction() for s in tracked.sessions)  # 끝난 뒤에도 쥔 트랜잭션이 없다
    with tracked.factory() as db:
        saved = db.get(models.Insight, insight_id)
        assert (saved.summary_md, saved.summary_md_en) == ("ko 요약", "en 요약")


def test_regenerate_thread_holds_no_transaction_while_summarizing(tracked, monkeypatch):
    token = _seed_user(tracked.factory)
    done = threading.Event()
    results: list[int] = []
    real_run_once = insights_runner.run_once

    first: list[int] = []

    def run_once(window_spec="6h", **kwargs):
        try:
            first.append(len(tracked.sessions))  # 이 뒤에 만든 세션이 스레드의 세션이다
            results.append(real_run_once(window_spec, **kwargs))
        finally:
            done.set()

    monkeypatch.setattr(insights_runner, "run_once", run_once)  # _run_regenerate가 부를 때 import한다
    with TestClient(_app(tracked.factory)) as client:
        tracked.timeline.clear()
        resp = client.post("/api/insights/regenerate", json={"window": "6h"},
                           headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200 and resp.json()["triggered"] is True
        assert done.wait(10) and results and results[0] > 0
    _assert_read_then_summaries_then_fresh_save(tracked.timeline, langs=["ko", "en"], first_session=first[0])


@pytest.mark.parametrize("lang", ["ko", "en"])
def test_stream_regenerate_holds_no_transaction_while_streaming(tracked, lang):
    token = _seed_user(tracked.factory)
    with TestClient(_app(tracked.factory)) as client:
        tracked.timeline.clear()
        tracked.sessions.clear()
        resp = client.post("/api/insights/stream-regenerate", json={"window": "6h", "lang": lang},
                           headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and "event: final" in resp.text and '"ok": true' in resp.text
    # 요청 세션(인증의 users 조회)과 generator 세션(통계 조회) 둘 다 스트림 동안 트랜잭션이 없다
    assert len(tracked.sessions) == 2
    _assert_stream_order(tracked.timeline, lang)


def _assert_stream_order(timeline, lang):
    calls = [entry for entry in timeline if entry[0] == "bedrock"]
    assert [c[1] for c in calls] == [lang]
    assert calls[0][2] == [], f"스트림 동안 열린 세션 트랜잭션: {calls[0][2]}"
    bedrock_at = _positions(timeline, lambda e: e[0] == "bedrock")[0]
    users = _positions(timeline, lambda e: e[0] == "sql" and "FROM users" in e[1])
    reads = _positions(timeline, lambda e: e[0] == "sql" and "FROM probe_results" in e[1])
    inserts = _positions(timeline, lambda e: e[0] == "sql" and e[1].lstrip().upper().startswith("INSERT INTO INSIGHTS"))
    assert users and reads and max(users + reads) < bedrock_at
    assert len(inserts) == 1 and inserts[0] > bedrock_at


# ───────────────────────────────────────────────────────────────────────
# PostgreSQL — 요약 동안 pg_locks가 비어 있고 lifespan과 같은 ALTER가 lock_timeout 2초 안에 끝난다
# ───────────────────────────────────────────────────────────────────────

PG_URL = os.environ.get("TEST_PG_URL")
_SCHEMA = "insights_locks_e2e"
# lifespan 마이그레이션 블록(main.py)과 같은 문장 — 열은 이미 있으므로 락만 잡았다 놓는다
_ALTERS = (
    "ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS is_auto INTEGER DEFAULT 0",
    "ALTER TABLE probe_results ADD COLUMN IF NOT EXISTS stop_reason TEXT",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS approved INTEGER DEFAULT 0",
)


@pytest.fixture()
def pg(monkeypatch):
    if not PG_URL:
        pytest.skip("TEST_PG_URL이 없다 — 로컬 PostgreSQL이 있을 때만 돈다")
    admin = create_engine(PG_URL, connect_args={"connect_timeout": 3})
    try:
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {_SCHEMA}"))
    except OperationalError as exc:
        admin.dispose()
        pytest.skip(f"PostgreSQL에 연결할 수 없다: {exc.orig}")
    options = {"options": f"-c search_path={_SCHEMA}", "connect_timeout": 3}
    engine = create_engine(PG_URL, connect_args=options)
    ddl = create_engine(PG_URL, connect_args=options)  # ALTER 전용 — 관찰자와 같은 스키마, 트랜잭션마다 SET LOCAL
    observer = create_engine(PG_URL, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3})
    models.Base.metadata.create_all(engine)
    seed(sessionmaker(bind=engine))
    factory = sessionmaker(bind=engine)
    monkeypatch.setenv("HIDDEN_MODEL_PATTERNS", "(1P)")
    monkeypatch.setattr(insights_runner, "datetime", FrozenDatetime)
    monkeypatch.setattr(insights_runner, "SessionLocal", factory)
    monkeypatch.setattr(insights_router, "SessionLocal", factory)
    seen: list[dict] = []

    def held_locks() -> list[tuple]:
        with observer.connect() as conn:
            return [tuple(r) for r in conn.execute(text(
                "SELECT c.relname, l.mode, a.state FROM pg_locks l "
                "JOIN pg_class c ON c.oid = l.relation JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_stat_activity a ON a.pid = l.pid "
                "WHERE n.nspname = :schema AND l.pid <> pg_backend_pid() ORDER BY 1, 2"), {"schema": _SCHEMA})]

    def try_alters() -> dict:
        out = {}
        for sql in _ALTERS:
            started = time.monotonic()
            try:
                with ddl.begin() as conn:
                    conn.execute(text("SET LOCAL lock_timeout = '2s'"))
                    conn.execute(text(sql))
                out[sql] = ("ok", round(time.monotonic() - started, 2))
            except OperationalError as exc:
                out[sql] = (type(exc.orig).__name__, round(time.monotonic() - started, 2))
        return out

    def on_call(lang):
        seen.append({"lang": lang, "locks": held_locks(), "alters": try_alters()})

    _install_fake_bedrock(monkeypatch, on_call)
    try:
        yield SimpleNamespace(factory=factory, seen=seen)
    finally:
        engine.dispose()
        ddl.dispose()
        observer.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        admin.dispose()


def _assert_lock_free(seen, langs):
    assert sorted(s["lang"] for s in seen) == sorted(langs)
    for s in seen:
        assert s["locks"] == [], f"{s['lang']} 요약 동안 남은 락: {s['locks']}"
        for sql, (outcome, elapsed) in s["alters"].items():
            assert outcome == "ok" and elapsed < 1.0, f"{s['lang']}: {sql} → {outcome} ({elapsed}s)"


def test_pg_run_once_summary_phase_holds_no_lock_and_the_startup_alter_succeeds(pg):
    insight_id = insights_runner.run_once("6h")
    assert insight_id > 0
    _assert_lock_free(pg.seen, ["ko", "en"])
    with pg.factory() as db:
        saved = db.get(models.Insight, insight_id)
        assert (saved.summary_md, saved.summary_md_en) == ("ko 요약", "en 요약")
        assert saved.model_breakdown  # 통계를 그대로 저장했다


def test_pg_stream_regenerate_holds_no_lock_while_streaming(pg):
    token = _seed_user(pg.factory)
    with TestClient(_app(pg.factory)) as client:
        resp = client.post("/api/insights/stream-regenerate", json={"window": "6h", "lang": "ko"},
                           headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200 and '"ok": true' in resp.text, resp.text
    _assert_lock_free(pg.seen, ["ko"])  # users(인증 조회) 락도 없다
