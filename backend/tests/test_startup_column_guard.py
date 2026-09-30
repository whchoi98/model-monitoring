"""lifespan 마이그레이션 블록의 열 확인 (2026-09-30 v2.32.2, 운영 기동 4번 중 2번 LockNotAvailable).

배경: 운영 backend 기동 두 번이 `ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS is_auto INTEGER DEFAULT 0`에서 정확히 5초
(lock_timeout) 뒤 LockNotAvailable로 'Migration block failed'였다. 두 번 모두 Insights 태스크가 Bedrock 요약을 기다리는 동안
probe_runs, probe_results의 ACCESS SHARE를 쥐고 있었다. PostgreSQL의 ADD COLUMN IF NOT EXISTS는 열이 있는지 보기 전에
ACCESS EXCLUSIVE부터 요청하므로 no-op이어도 읽기 트랜잭션 하나에 막히고, 기다리는 동안 그 뒤에 온 평범한 읽기까지 줄을 세운다.
블록은 한 트랜잭션이라 실패하면 뒤의 라벨 rename, 삭제도 함께 롤백된다.

지금은 블록이 advisory 락을 잡은 뒤 같은 트랜잭션에서 카탈로그(sqlalchemy inspect)로 다섯 열을 확인하고, 빠진 열만 예전과 같은
ALTER 문장으로 더한다(main._add_missing_startup_columns). 고정하는 것:
- SQLite: 열이 다 있으면 ALTER 0건이다. 빠진 열만 _STARTUP_COLUMNS 순서로 더하고, 다시 부르면 0건이다. 다섯 열이 모두 없는
  옛 스키마는 ORM과 같은 열이 되고 기존 행은 기본값을 읽는다.
- PostgreSQL 문장 형태(가짜 inspector): 다섯 열이 모두 없으면 v2.32.1과 글자 하나까지 같은 ALTER 5개를 같은 순서로 실행하고,
  테이블마다 카탈로그를 한 번만 읽는다. _STARTUP_COLUMNS의 타입과 기본값은 ORM 선언과 같다.
- PostgreSQL 증명(TEST_PG_URL이 있을 때만): 세션 A가 probe_runs, probe_results, users, insights를 읽은 트랜잭션을 열어 둔 채로
  실제 main.lifespan의 마이그레이션이 lock_timeout(5초)보다 훨씬 빨리 실패 없이 끝나고, 라벨 rename과 삭제도 적용되며, advisory
  락은 남지 않는다(v2.32.1은 5초 뒤 실패). 열이 정말 빠져 있으면 그 ALTER는 A를 기다리고(ACCESS EXCLUSIVE 미승인), A가 끝나면
  그 열을 더한다.
  예: docker run -d --rm --name <이름> -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=pg postgres:16 뒤
  TEST_PG_URL=postgresql://postgres:pg@127.0.0.1:55432/postgres python3.12 -m pytest tests/test_startup_column_guard.py
"""

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import StaticPool

import label_repair
import main
import models
import prober

# v2.32.1 main.py lifespan이 기동마다 실행하던 ALTER 5개, 순서 그대로
V2321_ALTERS = [
    "ALTER TABLE probe_runs ADD COLUMN IF NOT EXISTS is_auto INTEGER DEFAULT 0",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS approved INTEGER DEFAULT 0",
    "ALTER TABLE insights ADD COLUMN IF NOT EXISTS summary_md_en TEXT",
    "ALTER TABLE probe_results ADD COLUMN IF NOT EXISTS category TEXT",
    "ALTER TABLE probe_results ADD COLUMN IF NOT EXISTS stop_reason TEXT",
]
STARTUP_TABLES = ["probe_runs", "users", "insights", "probe_results"]
# v2 초기 스키마 — 다섯 열이 모두 없다
V1_DDL = (
    "CREATE TABLE probe_runs (id INTEGER PRIMARY KEY, created_at DATETIME, prompt TEXT NOT NULL, status TEXT)",
    "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT NOT NULL, password_hash TEXT NOT NULL)",
    "CREATE TABLE insights (id INTEGER PRIMARY KEY, summary_md TEXT NOT NULL)",
    "CREATE TABLE probe_results (id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, model_name TEXT NOT NULL)",
)


def _sqlite_engine():
    return create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})


def _capture(engine) -> list[str]:
    log: list[str] = []
    event.listen(engine, "before_cursor_execute", lambda conn, cur, stmt, params, ctx, many: log.append(stmt))
    return log


def _alters(log: list[str]) -> list[str]:
    return [s for s in log if s.lstrip().upper().startswith("ALTER")]


def _columns(engine, table: str) -> list[str]:
    return [c["name"] for c in inspect(engine).get_columns(table)]


# ───────────────────────────────────────────────────────────────────────
# SQLite — 확인 로직
# ───────────────────────────────────────────────────────────────────────

def test_all_columns_present_runs_no_alter():
    engine = _sqlite_engine()
    models.Base.metadata.create_all(engine)
    log = _capture(engine)
    with engine.begin() as conn:
        assert main._add_missing_startup_columns(conn) == []
    assert _alters(log) == []
    assert log, "the catalog must still be read"


def test_only_missing_columns_are_added_in_order_and_a_rerun_is_a_no_op():
    engine = _sqlite_engine()
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:  # 인덱스에 들어 있지 않은 열 두 개를 뺀다
        conn.execute(text("ALTER TABLE insights DROP COLUMN summary_md_en"))
        conn.execute(text("ALTER TABLE probe_results DROP COLUMN stop_reason"))
    log = _capture(engine)
    with engine.begin() as conn:
        added = main._add_missing_startup_columns(conn)
    assert added == ["insights.summary_md_en", "probe_results.stop_reason"]
    assert _alters(log) == [
        "ALTER TABLE insights ADD COLUMN summary_md_en TEXT",
        "ALTER TABLE probe_results ADD COLUMN stop_reason TEXT",
    ]
    assert "summary_md_en" in _columns(engine, "insights") and "stop_reason" in _columns(engine, "probe_results")

    log.clear()
    with engine.begin() as conn:
        assert main._add_missing_startup_columns(conn) == []
    assert _alters(log) == []


def test_v1_schema_gets_every_column_with_its_default():
    engine = _sqlite_engine()
    with engine.begin() as conn:
        for ddl in V1_DDL:
            conn.execute(text(ddl))
        conn.execute(text("INSERT INTO probe_runs (id, prompt, status) VALUES (1, 'p', 'completed')"))
        conn.execute(text("INSERT INTO users (id, username, password_hash) VALUES (1, 'a@example.com', 'x')"))
    with engine.begin() as conn:
        added = main._add_missing_startup_columns(conn)
    assert added == [f"{t}.{c}" for t, c, _ in main._STARTUP_COLUMNS]
    for table, column, _ in main._STARTUP_COLUMNS:
        assert column in _columns(engine, table), (table, column)
    with engine.connect() as conn:  # 기존 행은 DEFAULT 0을 읽는다 (v2.32.1 ALTER와 같은 기본값)
        assert conn.execute(text("SELECT is_auto FROM probe_runs")).scalar() == 0
        assert conn.execute(text("SELECT approved FROM users")).scalar() == 0


def test_startup_columns_match_the_orm_declarations():
    """확인 대상 다섯 열의 타입과 기본값이 ORM과 같다 — create_all로 만든 DB와 ALTER로 더한 DB가 같은 스키마다."""
    assert [(t, c) for t, c, _ in main._STARTUP_COLUMNS] == [
        ("probe_runs", "is_auto"), ("users", "approved"), ("insights", "summary_md_en"),
        ("probe_results", "category"), ("probe_results", "stop_reason"),
    ]
    for table, column, ddl in main._STARTUP_COLUMNS:
        col = models.Base.metadata.tables[table].c[column]
        assert ddl.split()[0] == str(col.type), (table, column)
        if "DEFAULT" in ddl:
            assert col.default is not None and ddl.endswith(f"DEFAULT {col.default.arg}"), (table, column)
        else:
            assert col.default is None, (table, column)


# ───────────────────────────────────────────────────────────────────────
# PostgreSQL 문장 형태 — 가짜 inspector
# ───────────────────────────────────────────────────────────────────────

class _FakeInspector:
    def __init__(self, present: dict[str, set[str]]):
        self.present = present
        self.calls: list[str] = []

    def get_columns(self, table):
        self.calls.append(table)
        return [{"name": name} for name in sorted(self.present.get(table, ()))]


class _RecordingPgConn:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self):
        self.sql: list[str] = []

    def execute(self, stmt, params=None):
        self.sql.append(str(stmt))


def _pg_run(monkeypatch, present):
    fake = _FakeInspector(present)
    monkeypatch.setattr(main, "sa_inspect", lambda conn: fake)
    conn = _RecordingPgConn()
    added = main._add_missing_startup_columns(conn)
    return added, conn.sql, fake.calls


def test_postgres_missing_columns_use_the_v2321_statements(monkeypatch):
    added, sql, calls = _pg_run(monkeypatch, {})
    assert sql == V2321_ALTERS
    assert added == [f"{t}.{c}" for t, c, _ in main._STARTUP_COLUMNS]
    assert calls == STARTUP_TABLES  # 테이블마다 카탈로그를 한 번만 읽는다


def test_postgres_existing_columns_emit_no_ddl(monkeypatch):
    present = {"probe_runs": {"id", "is_auto"}, "users": {"approved"}, "insights": {"summary_md_en"},
               "probe_results": {"category", "stop_reason"}}
    added, sql, calls = _pg_run(monkeypatch, present)
    assert (added, sql, calls) == ([], [], STARTUP_TABLES)

    present["probe_results"] = {"category"}
    added, sql, _ = _pg_run(monkeypatch, present)
    assert (added, sql) == (["probe_results.stop_reason"], [V2321_ALTERS[-1]])


# ───────────────────────────────────────────────────────────────────────
# PostgreSQL 증명 — 열린 읽기 트랜잭션 아래의 실제 lifespan
# ───────────────────────────────────────────────────────────────────────

PG_URL = os.environ.get("TEST_PG_URL")
_SCHEMA = "startup_column_guard"
_LOCK_TIMEOUT_S = 5.0  # main.lifespan의 SET LOCAL lock_timeout = '5000'
_OLD_LABEL, _NEW_LABEL = "Claude Opus 4.7 (Global)", "Bedrock Claude Opus 4.7 (Global)"
_REMOVED = ("Bedrock Claude Sonnet 4.5 (Global)", "Bedrock Nova Pro (US)")


class _NoStartThread:
    """lifespan의 perf-indexes 스레드를 띄우지 않는다 (테스트 스키마 정리와 겹치지 않게)."""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


@pytest.fixture()
def pg_url():
    if not PG_URL:
        pytest.skip("TEST_PG_URL이 없다 — 로컬 PostgreSQL이 있을 때만 돈다")
    probe = create_engine(PG_URL, connect_args={"connect_timeout": 3})
    try:
        with probe.connect() as conn:
            conn.execute(text("SELECT 1"))
    except OperationalError as exc:
        pytest.skip(f"PostgreSQL에 연결할 수 없다: {exc.orig}")
    finally:
        probe.dispose()
    return PG_URL


@pytest.fixture()
def pg(pg_url):
    """전용 스키마에 create_all로 만든 테이블과 옛 라벨, 제거된 모델 행. observer는 AUTOCOMMIT."""
    observer = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with observer.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_SCHEMA}"))
    engine = create_engine(pg_url, connect_args={"options": f"-c search_path={_SCHEMA}", "connect_timeout": 3})
    try:
        models.Base.metadata.create_all(engine)
        now = datetime.now(timezone.utc)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO probe_runs (id, created_at, prompt, status, is_auto) "
                              "VALUES (1, :now, 'auto', 'completed', 1)"), {"now": now})
            for i, name in enumerate((_OLD_LABEL, *_REMOVED, "Bedrock Claude Sonnet 5 (Global)"), start=1):
                conn.execute(text("INSERT INTO probe_results (id, run_id, model_id, model_name, timestamp, prompt, status) "
                                  "VALUES (:id, 1, 'm', :name, :now, 'p', 'success')"),
                             {"id": i, "name": name, "now": now})
            conn.execute(text("INSERT INTO users (id, username, password_hash, approved) VALUES (1, 'admin', 'x', 1)"))
            conn.execute(text("INSERT INTO insights (id, window_start, window_end, summary_md) "
                              "VALUES (1, :now, :now, 'ko')"), {"now": now})
        yield SimpleNamespace(engine=engine, observer=observer)
    finally:
        engine.dispose()
        with observer.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        observer.dispose()


def _patch_lifespan(monkeypatch, engine):
    """실제 main.lifespan을 engine에 대해 돌게 하고, 마이그레이션 블록 밖의 단계는 끈다."""
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "create_tables", lambda: None)
    monkeypatch.setattr(main, "_seed_default_admin", lambda: None)
    monkeypatch.setattr(main, "_ensure_price_schema", lambda: None)
    monkeypatch.setattr(main, "threading", SimpleNamespace(Thread=_NoStartThread))
    monkeypatch.setattr(prober, "_discover_anthropic_models", lambda: None)
    monkeypatch.setattr(prober, "_register_openai_models", lambda: None)
    monkeypatch.setattr(label_repair, "repair_model_labels", lambda *args, **kwargs: None)


def _run_lifespan() -> float:
    async def enter_and_exit():
        async with main.lifespan(main.app):
            pass

    started = time.monotonic()
    asyncio.run(enter_and_exit())
    return time.monotonic() - started


def _open_reader(engine, tables):
    """세션 A — 읽기만 하고 트랜잭션을 열어 둔다 (Insights run_once가 Bedrock을 기다리는 동안과 같다)."""
    reader = engine.connect()
    for table in tables:
        reader.execute(text(f"SELECT count(*) FROM {table}")).scalar()
    return reader, reader.execute(text("SELECT pg_backend_pid()")).scalar()


def _locks(observer, pid=None):
    sql = ("SELECT c.relname, l.mode, l.granted, l.pid FROM pg_locks l JOIN pg_class c ON c.oid = l.relation "
           "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = :schema")
    with observer.connect() as conn:
        rows = conn.execute(text(sql), {"schema": _SCHEMA}).fetchall()
    return [r for r in rows if pid is None or r.pid == pid]


def _advisory_holders(observer) -> int:
    with observer.connect() as conn:
        return conn.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND objid = 917350001")).scalar()


def _failures(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("Migration block failed")]


def test_pg_existing_columns_do_not_wait_for_an_open_reader(pg, monkeypatch, caplog):
    reader, pid = _open_reader(pg.engine, STARTUP_TABLES)
    try:
        held = {(r.relname, r.mode) for r in _locks(pg.observer, pid)}
        assert {(t, "AccessShareLock") for t in STARTUP_TABLES} <= held
        _patch_lifespan(monkeypatch, pg.engine)
        with caplog.at_level(logging.INFO, logger="main"):
            elapsed = _run_lifespan()
        assert _failures(caplog) == []
        assert elapsed < _LOCK_TIMEOUT_S / 2, f"migration waited {elapsed:.2f}s"  # v2.32.1: fails after 5.0 s
        assert reader.in_transaction()  # A는 끝까지 락을 쥐고 있었다
        assert {(r.relname, r.mode) for r in _locks(pg.observer, pid)} == held
    finally:
        reader.rollback()
        reader.close()

    with pg.engine.connect() as conn:  # 같은 트랜잭션의 라벨 rename, 삭제도 적용됐다
        names = conn.execute(text("SELECT model_name FROM probe_results ORDER BY id")).scalars().all()
    assert names == [_NEW_LABEL, "Bedrock Claude Sonnet 5 (Global)"]
    assert _advisory_holders(pg.observer) == 0
    assert not any("Startup columns added" in r.getMessage() for r in caplog.records)


def test_pg_missing_column_waits_for_the_reader_then_is_added(pg, monkeypatch, caplog):
    with pg.engine.begin() as conn:
        conn.execute(text("ALTER TABLE probe_runs DROP COLUMN is_auto"))
    reader, pid = _open_reader(pg.engine, ["probe_runs"])
    _patch_lifespan(monkeypatch, pg.engine)
    result: dict = {}

    def run():
        try:
            result["elapsed"] = _run_lifespan()
        except BaseException as exc:  # noqa: BLE001 — 테스트 스레드 예외를 본문에 넘긴다
            result["error"] = exc

    with caplog.at_level(logging.INFO, logger="main"):
        worker = threading.Thread(target=run, name="lifespan-under-reader")
        try:
            worker.start()
            deadline = time.monotonic() + 3.0
            waiting = []
            while time.monotonic() < deadline and not waiting:
                waiting = [r for r in _locks(pg.observer)
                           if r.relname == "probe_runs" and r.mode == "AccessExclusiveLock" and not r.granted]
                time.sleep(0.05)
            assert waiting, "the ALTER for the missing column should wait for the reader"
            assert worker.is_alive()
        finally:
            reader.rollback()  # A가 끝난다 → ALTER가 락을 잡는다
            reader.close()
            worker.join(10)
    assert not worker.is_alive() and "error" not in result
    assert _failures(caplog) == []
    assert result["elapsed"] < _LOCK_TIMEOUT_S
    assert "is_auto" in _columns(pg.engine, "probe_runs")
    with pg.engine.connect() as conn:
        assert conn.execute(text("SELECT is_auto FROM probe_runs")).scalars().all() == [0]
        names = conn.execute(text("SELECT model_name FROM probe_results ORDER BY id")).scalars().all()
    assert names == [_NEW_LABEL, "Bedrock Claude Sonnet 5 (Global)"]
    assert any(r.getMessage() == "Startup columns added: probe_runs.is_auto" for r in caplog.records)
    assert _advisory_holders(pg.observer) == 0
