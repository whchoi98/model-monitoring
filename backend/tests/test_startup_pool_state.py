"""기동이 풀 커넥션에 남기는 것 — advisory 락과 세션 설정 (2026-09-30 v2.32.2, postgres:16에서 재현).

배경:
1. advisory 락 누수: lifespan 마이그레이션 블록은 세션 수준 `pg_advisory_lock(917350001)`을 잡고 finally에서
   `pg_advisory_unlock`을 불렀다. 블록이 DB 오류로 실패하면 unlock이 이미 중단된 트랜잭션 안에서 InFailedSqlTransaction으로
   실패하고(삼켜진다), 락은 풀로 돌아간 커넥션(state idle)에 남았다. 그 커넥션이 재활용될 때까지 다음 기동(다른 태스크)의
   `pg_advisory_lock`은 lock_timeout(5초)을 기다린 뒤 실패했다.
2. 세션 설정 누수: 블록의 `SET statement_timeout`, `SET lock_timeout`, ensure_performance_indexes의 AUTOCOMMIT
   `SET statement_timeout = '600000'`, label_repair의 `SET statement_timeout`이 풀 커넥션에 남았다. 평범한 기동 뒤 쉬는 풀
   커넥션에서 lock_timeout 5초, statement_timeout 10분과 1분이 보였다. 설정값은 database.py가 커넥션 옵션
   (`-c statement_timeout`, DB_STATEMENT_TIMEOUT_MS, 기본 30초)으로 거는 값이고 lock_timeout은 0이다.

지금은 블록이 한 트랜잭션에서 `SET LOCAL` 두 개 뒤 `pg_advisory_xact_lock(917350001)`을 잡는다. 락은 커밋이나 롤백에 풀리고
unlock 문장이 없다. label_repair도 `SET LOCAL`이다. 트랜잭션 밖(AUTOCOMMIT)에서 도는 CONCURRENTLY 인덱스 경로는 `SET LOCAL`이
듣지 않으므로 finally에서 `RESET statement_timeout`으로 세션 기본값(커넥션 옵션 값, pg_settings.source = 'client')에 되돌리고,
RESET조차 못 하면 그 커넥션을 풀에서 버린다(invalidate).

고정하는 것:
- 문장 형태(가짜 커넥션, 항상 돈다): 블록의 첫 세 문장은 `SET LOCAL statement_timeout`, `SET LOCAL lock_timeout`,
  `pg_advisory_xact_lock(917350001)`이고 세션 수준 SET, lock, unlock은 없다. 블록이 실패하면 그 뒤로 문장이 없다. 인덱스 경로는
  마지막이 RESET이고, CREATE INDEX가 실패해도 RESET한 뒤 예외를 넘기며, RESET이 실패하면 커넥션을 invalidate한다.
  label_repair는 `SET LOCAL statement_timeout`이다.
- PostgreSQL(TEST_PG_URL이 있을 때만): 평범한 lifespan(모델 등록만 끈다) 뒤 풀의 커넥션 전부가 새 커넥션과 같은
  statement_timeout(설정값, 출처 client)과 lock_timeout(0)을 보인다. 블록, 인덱스, 라벨 복구 각각도 그렇고, 인덱스 빌드가 실패해도
  그렇다. 블록을 강제로 실패시키면 advisory 락이 남지 않고, 풀을 그대로 둔 채 다음 태스크(새 풀)의 lifespan이 기다리지 않고 락을
  잡아 열을 더한다(v2.32.1: 5초 뒤 실패). ALTER 뒤 강제 실패와 커밋 실패는 `Startup columns added`를 남기지 않는다. 다른 세션이
  917350001을 쥐고 있으면 블록은 여전히 lock_timeout(5초) 뒤 포기하고 기동은 계속한다.
  예: docker run -d --rm --name <이름> -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=pg postgres:16 뒤
  TEST_PG_URL=postgresql://postgres:pg@127.0.0.1:55432/postgres python3.12 -m pytest tests/test_startup_pool_state.py
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
from sqlalchemy.orm import sessionmaker

import auth
import database
import label_repair
import main
import models
import prober

BLOCK_HEAD = [
    "SET LOCAL statement_timeout = '30000'",
    "SET LOCAL lock_timeout = '5000'",
    "SELECT pg_advisory_xact_lock(917350001)",
]


class _NoStartThread:
    """lifespan의 perf-indexes 스레드를 띄우지 않는다."""

    def __init__(self, *args, **kwargs):
        pass

    def start(self):
        pass


def _switch_off_other_steps(monkeypatch):
    """마이그레이션 블록 밖의 기동 단계를 끈다."""
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


def _messages(caplog, prefix: str) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(prefix)]


# ───────────────────────────────────────────────────────────────────────
# 문장 형태 — 가짜 커넥션
# ───────────────────────────────────────────────────────────────────────

class _RecordingPgConn:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, fail_on: str | None = None):
        self.sql: list[str] = []
        self.fail_on = fail_on

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append(sql)
        if self.fail_on and sql.startswith(self.fail_on):
            raise RuntimeError(f"forced failure at {sql}")


class _Begin:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc):
        return False


def _fake_block(monkeypatch, fail_on=None) -> _RecordingPgConn:
    conn = _RecordingPgConn(fail_on)
    present = [{"name": column} for _, column, _ in main._STARTUP_COLUMNS]
    monkeypatch.setattr(main, "sa_inspect", lambda c: SimpleNamespace(get_columns=lambda table: present))
    monkeypatch.setattr(main, "engine", SimpleNamespace(dialect=conn.dialect, begin=lambda: _Begin(conn)))
    _switch_off_other_steps(monkeypatch)
    return conn


def test_block_scopes_its_settings_and_the_advisory_lock_to_the_transaction(monkeypatch, caplog):
    conn = _fake_block(monkeypatch)
    with caplog.at_level(logging.INFO, logger="main"):
        _run_lifespan()
    assert _messages(caplog, "Migration block failed") == []
    assert conn.sql[:3] == BLOCK_HEAD
    assert conn.sql[3].startswith("DELETE FROM probe_results")  # 열이 다 있으면 DDL 없이 곧바로 삭제
    # 세션 수준 SET 없음 (UPDATE … SET model_name은 SET으로 시작하지 않는다)
    assert not any(s.startswith("SET ") and not s.startswith("SET LOCAL ") for s in conn.sql)
    assert not any("pg_advisory_lock(" in s or "pg_advisory_unlock" in s for s in conn.sql)


def test_failed_block_issues_nothing_after_the_failure(monkeypatch, caplog):
    """v2.32.1은 실패 뒤 중단된 트랜잭션에서 pg_advisory_unlock을 불렀고, 그 문장이 실패해 세션 락이 남았다."""
    conn = _fake_block(monkeypatch, fail_on="DELETE FROM probe_results")
    with caplog.at_level(logging.INFO, logger="main"):
        _run_lifespan()
    assert len(_messages(caplog, "Migration block failed")) == 1
    assert conn.sql[:3] == BLOCK_HEAD
    assert conn.sql[-1].startswith("DELETE FROM probe_results")  # 실패한 문장이 마지막이다
    assert _messages(caplog, "Startup columns added") == []


class _IndexConn:
    """ensure_performance_indexes의 AUTOCOMMIT 커넥션. fail_on으로 시작하는 문장은 한 번 실패한다."""

    def __init__(self, fail_on=()):
        self.sql: list[str] = []
        self.fail_on = list(fail_on)
        self.invalidated = False

    def execution_options(self, **kw):
        assert kw == {"isolation_level": "AUTOCOMMIT"}
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.sql.append(sql)
        for prefix in self.fail_on:
            if sql.startswith(prefix):
                self.fail_on.remove(prefix)
                raise RuntimeError(f"forced failure at {sql}")
        return SimpleNamespace(first=lambda: None)

    def invalidate(self):
        self.invalidated = True


def _index_engine(conn):
    return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: conn)


def test_index_path_resets_the_statement_timeout_last():
    conn = _IndexConn()
    models.ensure_performance_indexes(_index_engine(conn))
    assert conn.sql[0] == "SET statement_timeout = '600000'"
    assert conn.sql[-1] == "RESET statement_timeout"
    assert sum(s.startswith("CREATE INDEX CONCURRENTLY") for s in conn.sql) == len(models._PERF_INDEXES)
    assert not conn.invalidated


def test_index_failure_still_resets_then_raises():
    conn = _IndexConn(fail_on=["CREATE INDEX CONCURRENTLY"])
    with pytest.raises(RuntimeError, match="forced failure"):
        models.ensure_performance_indexes(_index_engine(conn))
    assert conn.sql[-2].startswith("CREATE INDEX CONCURRENTLY") and conn.sql[-1] == "RESET statement_timeout"
    assert not conn.invalidated


@pytest.mark.parametrize("index_fails", [False, True])
def test_index_path_discards_a_connection_it_cannot_reset(index_fails):
    """RESET조차 실패한 커넥션(끊긴 소켓 등)은 풀로 돌려보내지 않는다. 인덱스 오류가 있으면 그 오류를 넘긴다."""
    conn = _IndexConn(fail_on=(["CREATE INDEX CONCURRENTLY"] if index_fails else []) + ["RESET statement_timeout"])
    if index_fails:
        with pytest.raises(RuntimeError, match="CREATE INDEX"):
            models.ensure_performance_indexes(_index_engine(conn))
    else:
        models.ensure_performance_indexes(_index_engine(conn))
    assert conn.sql[-1] == "RESET statement_timeout"
    assert conn.invalidated


def test_label_repair_scopes_its_statement_timeout_to_the_transaction():
    conn = _RecordingPgConn()
    conn.execute = lambda stmt, params=None: conn.sql.append(str(stmt)) or SimpleNamespace(fetchall=lambda: [])
    pg = SimpleNamespace(dialect=conn.dialect, begin=lambda: _Begin(conn))
    assert label_repair.repair_model_labels(pg, {"m": "Bedrock M (Global)"}) == 0
    assert conn.sql[0] == "SET LOCAL statement_timeout = '60000'"
    assert not any(s.startswith("SET statement_timeout") for s in conn.sql)


# ───────────────────────────────────────────────────────────────────────
# PostgreSQL 증명 — 풀 커넥션의 설정과 advisory 락
# ───────────────────────────────────────────────────────────────────────

PG_URL = os.environ.get("TEST_PG_URL")
_SCHEMA = "startup_pool_state"
# 블록의 30000과 다르게 둔다 — 같으면 블록의 세션 SET이 남아도 값으로는 구별되지 않는다(출처는 따로 본다).
_CONFIGURED_MS = 45678
_OLD_LABEL, _NEW_LABEL = "Claude Opus 4.7 (Global)", "Bedrock Claude Opus 4.7 (Global)"
_SETTINGS_SQL = ("SELECT name, setting, source FROM pg_settings "
                 "WHERE name IN ('statement_timeout', 'lock_timeout') ORDER BY name")


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


def _connect_args() -> dict:
    """database.py의 운영 커넥션 인자에 테스트 스키마와 구별되는 statement_timeout만 바꿔 넣는다."""
    return {**database._PG_CONNECT_ARGS, "connect_timeout": 3,
            "options": f"-c statement_timeout={_CONFIGURED_MS} -c search_path={_SCHEMA}"}


@pytest.fixture()
def pg(pg_url):
    """전용 스키마(create_all, 옛 라벨 행)와 backend 태스크 하나에 해당하는 풀을 만드는 new_task(). observer는 AUTOCOMMIT."""
    observer = create_engine(pg_url, isolation_level="AUTOCOMMIT")
    with observer.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_SCHEMA}"))
    engines = []

    def new_task():
        eng = create_engine(pg_url, pool_pre_ping=True, pool_size=5, max_overflow=5, connect_args=_connect_args())
        engines.append(eng)
        return eng

    try:
        setup = new_task()
        models.Base.metadata.create_all(setup)
        now = datetime.now(timezone.utc)
        with setup.begin() as conn:
            conn.execute(text("INSERT INTO probe_runs (id, created_at, prompt, status, is_auto) "
                              "VALUES (1, :now, 'auto', 'completed', 1)"), {"now": now})
            conn.execute(text("INSERT INTO probe_results (id, run_id, model_id, model_name, timestamp, prompt, status) "
                              "VALUES (1, 1, 'm', :name, :now, 'p', 'success')"), {"name": _OLD_LABEL, "now": now})
        setup.dispose()
        yield SimpleNamespace(new_task=new_task, observer=observer)
    finally:
        for eng in engines:
            eng.dispose()
        with observer.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        observer.dispose()


def _fresh_settings(url) -> dict:
    """같은 커넥션 인자로 새로 연 커넥션의 설정 — 풀 커넥션이 돌아가야 할 값."""
    eng = create_engine(url, connect_args=_connect_args())
    try:
        with eng.connect() as conn:
            return {name: (setting, source) for name, setting, source in conn.execute(text(_SETTINGS_SQL))}
    finally:
        eng.dispose()


def _pooled_settings(engine) -> list[dict]:
    """풀에 들어 있는 커넥션을 한꺼번에 모두 꺼내 각자의 설정을 읽는다. 새 커넥션은 열지 않는다."""
    opened: list[int] = []

    def on_connect(dbapi_conn, record):
        opened.append(1)

    event.listen(engine, "connect", on_connect)
    conns = [engine.connect() for _ in range(engine.pool.checkedin())]
    try:
        return [{name: (setting, source) for name, setting, source in c.execute(text(_SETTINGS_SQL))} for c in conns]
    finally:
        for c in conns:
            c.close()
        event.remove(engine, "connect", on_connect)
        assert opened == [], "checking out the pooled connections must not open a new one"


def _assert_pool_at_configured_settings(pg_url, engine):
    fresh = _fresh_settings(pg_url)
    assert fresh == {"lock_timeout": ("0", "default"), "statement_timeout": (str(_CONFIGURED_MS), "client")}
    pooled = _pooled_settings(engine)
    assert pooled, "the startup step should have returned at least one connection to the pool"
    assert pooled == [fresh] * len(pooled)


def _advisory_holders(observer) -> list:
    with observer.connect() as conn:
        return conn.execute(text("SELECT l.pid, a.state FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid "
                                 "WHERE l.locktype = 'advisory' AND l.objid = 917350001")).fetchall()


def _columns(engine, table: str) -> list[str]:
    return [c["name"] for c in inspect(engine).get_columns(table)]


def _labels(engine) -> list[str]:
    with engine.connect() as conn:
        return conn.execute(text("SELECT model_name FROM probe_results ORDER BY id")).scalars().all()


class _RecordedThreads:
    """lifespan이 띄우는 스레드(perf-indexes)를 그대로 띄우고 기록해 테스트가 join한다."""

    def __init__(self):
        self.started: list[threading.Thread] = []

    def Thread(self, *args, **kwargs):  # noqa: N802 — threading.Thread 자리를 대신한다
        thread = threading.Thread(*args, **kwargs)
        self.started.append(thread)
        return thread


def test_pg_normal_lifespan_leaves_every_pooled_connection_at_the_configured_settings(pg, pg_url, monkeypatch, caplog):
    """모델 등록(네트워크)만 끄고 블록, perf-indexes 스레드, admin seed, 라벨 복구, 단가 열과 seed를 모두 실제로 돌린다."""
    engine = pg.new_task()
    threads = _RecordedThreads()
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "create_tables", lambda: models.Base.metadata.create_all(engine))
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(main, "threading", SimpleNamespace(Thread=threads.Thread))
    monkeypatch.setattr(prober, "_discover_anthropic_models", lambda: None)
    monkeypatch.setattr(prober, "_register_openai_models", lambda: None)
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "startup-pool-state")
    monkeypatch.setattr(auth, "hash_password", lambda password: "hashed")  # bcrypt 백엔드는 이 테스트의 관심 밖
    with caplog.at_level(logging.INFO):
        _run_lifespan()
        for thread in threads.started:
            thread.join(60)
    assert [t.name for t in threads.started] == ["perf-indexes"] and not threads.started[0].is_alive()
    assert "Performance indexes ensured (background)." in [r.getMessage() for r in caplog.records]
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
    assert _labels(engine) == [_NEW_LABEL]
    with engine.connect() as conn:  # admin seed와 단가 seed도 이 풀의 커넥션으로 커밋됐다
        assert conn.execute(text("SELECT username, approved FROM users")).all() == [("admin", 1)]
        assert conn.execute(text("SELECT count(*) FROM price_history")).scalar() > 0
    _assert_pool_at_configured_settings(pg_url, engine)
    assert _advisory_holders(pg.observer) == []


def test_pg_migration_block_restores_the_pooled_connection(pg, pg_url, monkeypatch, caplog):
    engine = pg.new_task()
    monkeypatch.setattr(main, "engine", engine)
    _switch_off_other_steps(monkeypatch)
    with caplog.at_level(logging.INFO, logger="main"):
        _run_lifespan()
    assert _messages(caplog, "Migration block failed") == []
    assert _labels(engine) == [_NEW_LABEL]
    _assert_pool_at_configured_settings(pg_url, engine)  # v2.32.1: lock_timeout 5000, statement_timeout 30000 (session)


def test_pg_index_build_restores_the_pooled_connection(pg, pg_url):
    engine = pg.new_task()
    models.ensure_performance_indexes(engine)
    _assert_pool_at_configured_settings(pg_url, engine)  # v2.32.1: statement_timeout 600000 (session)


def test_pg_label_repair_restores_the_pooled_connection(pg, pg_url):
    engine = pg.new_task()
    with engine.begin() as conn:
        conn.execute(text("UPDATE probe_results SET model_id = 'x', model_name = 'old'"))
    assert label_repair.repair_model_labels(engine, {"x": "Bedrock X (Global)"}) == 1
    _assert_pool_at_configured_settings(pg_url, engine)  # v2.32.1: statement_timeout 60000 (session)


def test_pg_failed_index_build_still_restores_the_pooled_connection(pg, pg_url):
    engine = pg.new_task()
    with engine.begin() as conn:  # ix_probe_results_model_name의 열이 없어 그 CREATE INDEX가 실패한다
        conn.execute(text("ALTER TABLE probe_results DROP COLUMN model_name"))
    with pytest.raises(Exception, match="model_name"):
        models.ensure_performance_indexes(engine)
    _assert_pool_at_configured_settings(pg_url, engine)


def test_pg_failed_block_leaves_no_advisory_lock_and_the_next_task_takes_it_at_once(pg, pg_url, monkeypatch, caplog):
    """ALTER 뒤 DB 오류로 블록이 실패한 태스크 A의 풀을 그대로 두고, 다음 태스크 B가 기동한다."""
    task_a = pg.new_task()
    with task_a.begin() as conn:
        conn.execute(text("ALTER TABLE insights DROP COLUMN summary_md_en"))
    real_add = main._add_missing_startup_columns

    def add_then_fail(conn):
        added = real_add(conn)
        assert added == ["insights.summary_md_en"]
        conn.execute(text("SELECT 1 / 0"))  # 트랜잭션을 중단시키는 DB 오류 (division_by_zero)
        return added

    _switch_off_other_steps(monkeypatch)
    monkeypatch.setattr(main, "engine", task_a)
    monkeypatch.setattr(main, "_add_missing_startup_columns", add_then_fail)
    with caplog.at_level(logging.INFO, logger="main"):
        _run_lifespan()
    assert len(_messages(caplog, "Migration block failed")) == 1
    assert _messages(caplog, "Startup columns added") == []  # 롤백된 열은 알리지 않는다
    assert "summary_md_en" not in _columns(task_a, "insights") and _labels(task_a) == [_OLD_LABEL]
    assert task_a.pool.checkedin() >= 1  # A의 커넥션은 풀에 남아 있다 (v2.32.1은 거기에 세션 락이 남았다)
    assert _advisory_holders(pg.observer) == []
    _assert_pool_at_configured_settings(pg_url, task_a)

    caplog.clear()
    task_b = pg.new_task()
    monkeypatch.setattr(main, "engine", task_b)
    monkeypatch.setattr(main, "_add_missing_startup_columns", real_add)
    with caplog.at_level(logging.INFO, logger="main"):
        elapsed = _run_lifespan()
    assert _messages(caplog, "Migration block failed") == []
    assert elapsed < 2.0, f"the next task waited {elapsed:.2f}s for the advisory lock"  # v2.32.1: fails after 5 s
    assert _messages(caplog, "Startup columns added") == ["Startup columns added: insights.summary_md_en"]
    assert "summary_md_en" in _columns(task_b, "insights") and _labels(task_b) == [_NEW_LABEL]
    assert _advisory_holders(pg.observer) == []


def test_pg_columns_added_is_logged_only_after_the_commit(pg, monkeypatch, caplog):
    """커밋 자체가 실패하면(여기서는 commit 이벤트가 한 번 예외) ALTER가 성공했어도 알리지 않고, 열도 락도 남지 않는다."""
    engine = pg.new_task()
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE probe_results DROP COLUMN stop_reason"))

    fired: list[int] = []

    def fail_commit_once(conn):
        if not fired:
            fired.append(1)
            raise RuntimeError("forced COMMIT failure")

    event.listen(engine, "commit", fail_commit_once)
    _switch_off_other_steps(monkeypatch)
    monkeypatch.setattr(main, "engine", engine)
    try:
        with caplog.at_level(logging.INFO, logger="main"):
            _run_lifespan()
    finally:
        event.remove(engine, "commit", fail_commit_once)
    assert fired == [1]
    assert len(_messages(caplog, "Migration block failed")) == 1
    assert _messages(caplog, "Startup columns added") == []
    assert "stop_reason" not in _columns(engine, "probe_results") and _labels(engine) == [_OLD_LABEL]
    assert _advisory_holders(pg.observer) == []


def test_pg_advisory_lock_wait_is_still_bounded_by_lock_timeout(pg, monkeypatch, caplog):
    """다른 세션이 917350001을 쥐고 있으면 블록은 lock_timeout(5초) 뒤 포기하고 기동은 계속한다 (SET LOCAL도 락 대기에 걸린다)."""
    holder = pg.observer.connect()
    try:
        holder.execute(text("SELECT pg_advisory_lock(917350001)"))
        engine = pg.new_task()
        _switch_off_other_steps(monkeypatch)
        monkeypatch.setattr(main, "engine", engine)
        with caplog.at_level(logging.INFO, logger="main"):
            elapsed = _run_lifespan()
        failures = [r for r in caplog.records if r.getMessage().startswith("Migration block failed")]
        assert len(failures) == 1 and "lock timeout" in str(failures[0].exc_info[1])
        assert 4.5 < elapsed < 8.0, f"the block gave up after {elapsed:.2f}s"
        assert _labels(engine) == [_OLD_LABEL]
        holder_pid = holder.execute(text("SELECT pg_backend_pid()")).scalar()
        assert [pid for pid, _ in _advisory_holders(pg.observer)] == [holder_pid]  # 기동 쪽은 아무것도 쥐고 있지 않다
    finally:
        holder.execute(text("SELECT pg_advisory_unlock(917350001)"))
        holder.close()
    assert _advisory_holders(pg.observer) == []
