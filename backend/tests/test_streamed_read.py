"""나눠 읽는 조회(yield_per)의 전체 시간 상한 — streamed_read.stream_rows (2026-09-30 v2.32.1 통합 리뷰).

database.py가 커넥션마다 거는 statement_timeout(DB_STATEMENT_TIMEOUT_MS, 기본 30초)은 문장 하나의 상한이다. yield_per로
나눠 읽는 조회는 PostgreSQL에서 psycopg2 이름 있는 커서(DECLARE 뒤 FETCH 반복)라 FETCH마다 따로 걸리고, FETCH 하나하나가
상한 안에 끝나면 전체는 얼마든지 길어진다. stream_rows는 같은 상한으로 전체 경과 시간을 재고, 넘으면 결과(서버 측 커서)를
닫은 뒤 StreamedReadTimeout을 던진다.

고정하는 것:
- 가짜 시계(streamed_read._clock): 상한을 넘는 순간 행 중간에서 멈추고, 예외를 던지기 전에 안쪽 반복자(= Query.__iter__
  생성기, 닫히면 결과와 DBAPI 커서를 닫는다)를 닫는다. 상한 안이면 행을 그대로 넘긴다. 0 이하는 상한 없음이다.
  기본 상한은 호출할 때 읽는 database._STATEMENT_TIMEOUT_MS다.
- SQLite 실제 커서: 멈춘 뒤 DBAPI 커서가 닫혀 있다(테스트가 안쪽 생성기를 붙잡고 있어 GC가 대신 닫을 수 없다).
- PostgreSQL 증명(TEST_PG_URL이 있을 때만): 행마다 pg_sleep을 부르는 조회에서 statement_timeout 1초는 한 번에 받는
  조회만 취소하고 yield_per 조회는 끝까지 읽는다. stream_rows는 1초 근처에서 멈추고 pg_cursors가 비어 있다.
  실제 라우트(/api/reliability/multi-channel, probe_results를 행마다 자는 뷰로 바꾼 스키마)도 1초 근처에서 503이고
  커넥션이 풀로 돌아온다. 상한을 끄면 같은 라우트가 statement_timeout 1초 아래에서 끝까지 읽는다.
  예: docker run -d --rm --name <이름> -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=pg postgres:16 뒤
  TEST_PG_URL=postgresql://postgres:pg@127.0.0.1:55432/postgres python3.12 -m pytest tests/test_streamed_read.py
"""

import os
import sqlite3
import time
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import database
import models
import streamed_read
from routers import reliability as reliability_router
from streamed_read import StreamedReadTimeout, stream_rows, stream_rows_or_503


class FakeClock:
    """부를 때마다 step초씩 간다 — 첫 호출(시작 시각)이 step, 행 k의 검사가 (k + 1) × step이다."""

    def __init__(self, step: float = 1.0) -> None:
        self.now = 0.0
        self.step = step
        self.calls = 0

    def __call__(self) -> float:
        self.calls += 1
        self.now += self.step
        return self.now


class TrackedRows:
    """Query.__iter__처럼 생성기를 돌려주고, 생성기가 닫힐 때(close 또는 끝) events에 남긴다."""

    def __init__(self, n: int, events: list) -> None:
        self.n = n
        self.events = events
        self.fetched = 0

    def __iter__(self):
        try:
            for i in range(self.n):
                self.fetched += 1
                yield i
        finally:
            self.events.append("closed")


@pytest.fixture()
def clock(monkeypatch):
    fake = FakeClock(step=1.0)
    monkeypatch.setattr(streamed_read, "_clock", fake)
    return fake


# ───────────────────────────────────────────────────────────────────────
# 가짜 시계 — 행 중간에서 멈추고, 던지기 전에 닫는다
# ───────────────────────────────────────────────────────────────────────


def test_abort_happens_mid_stream_and_closes_the_inner_iterator_before_raising(clock, caplog):
    events: list[str] = []
    source = TrackedRows(100, events)
    inner = iter(source)  # 붙잡아 둔다 — 도우미가 닫지 않으면 GC도 닫지 못한다
    got: list[int] = []
    with caplog.at_level("WARNING", logger="streamed_read"):
        try:
            for row in stream_rows(inner, what="GET /api/test window='7d'", timeout_ms=5000):
                got.append(row)
        except StreamedReadTimeout as exc:
            events.append("raised")
            error = exc
    assert got == [0, 1, 2, 3, 4]  # 행 6의 검사에서 경과 6초 > 5초
    assert source.fetched == 6 < source.n  # 중간에서 멈췄다
    assert events == ["closed", "raised"]  # 서버 측 커서(결과)를 먼저 닫고 던진다
    assert inner.gi_frame is None
    assert (error.what, error.elapsed_s, error.limit_s, error.rows) == ("GET /api/test window='7d'", 6.0, 5.0, 5)
    assert str(error) == "DB 조회가 5초 상한을 넘어 중단했습니다: GET /api/test window='7d' (6.0초, 5행)"
    (record,) = [r for r in caplog.records if r.name == "streamed_read"]
    assert record.levelname == "WARNING"
    assert record.getMessage() == (
        "streamed read over the 5s limit, aborted: GET /api/test window='7d' (elapsed 6.0s, 5 rows)"
    )


def test_rows_within_the_limit_pass_through_unchanged(clock):
    events: list[str] = []
    rows = [(i, f"model-{i % 3}", None if i % 4 else 1.5) for i in range(40)]
    assert list(stream_rows(rows, what="t", timeout_ms=60_000)) == rows  # 41초 < 60초
    got = list(stream_rows(TrackedRows(40, events), what="t", timeout_ms=60_000))
    assert got == list(range(40)) and events == ["closed"]


def test_exactly_the_limit_is_not_over_it(clock):
    # 행 k의 검사 = 경과 k초. 5000ms 상한에서 행 5(경과 5초)는 넘지 않고, 행 6(6초)이 넘는다.
    with pytest.raises(StreamedReadTimeout) as exc:
        list(stream_rows(range(10), what="t", timeout_ms=5000))
    assert exc.value.rows == 5


@pytest.mark.parametrize("timeout_ms", [0, -1])
def test_zero_or_negative_limit_disables_the_bound_like_statement_timeout_0(clock, timeout_ms):
    assert list(stream_rows(range(500), what="t", timeout_ms=timeout_ms)) == list(range(500))


def test_default_limit_is_database_statement_timeout_read_at_call_time(clock, monkeypatch):
    assert streamed_read.default_timeout_ms() == database._STATEMENT_TIMEOUT_MS
    assert database._PG_CONNECT_ARGS["options"] == f"-c statement_timeout={database._STATEMENT_TIMEOUT_MS}"
    monkeypatch.setattr(database, "_STATEMENT_TIMEOUT_MS", 3000)
    with pytest.raises(StreamedReadTimeout) as exc:
        list(stream_rows(range(100), what="t"))
    assert exc.value.limit_s == 3.0 and exc.value.rows == 3


def test_the_clock_starts_before_the_query_executes(clock):
    """Query는 첫 next()에서 실행된다(DECLARE + 첫 FETCH) — 실행 시간도 상한에 든다."""
    order: list[str] = []

    class LazyQuery:
        def __iter__(self):
            order.append(f"execute at {clock.now:g}")
            yield from range(3)

    list(stream_rows(LazyQuery(), what="t", timeout_ms=60_000))
    assert order == ["execute at 1"]  # 시작 시각(1초)을 잰 뒤에 실행했다


def test_a_consumer_exception_still_closes_the_inner_iterator(clock):
    events: list[str] = []
    inner = iter(TrackedRows(100, events))
    with pytest.raises(ZeroDivisionError):
        for row in stream_rows(inner, what="t", timeout_ms=60_000):
            if row == 3:
                1 / 0
    assert events == ["closed"] and inner.gi_frame is None


def test_close_error_does_not_hide_the_timeout(clock, caplog):
    class BadClose:
        def __iter__(self):
            return self

        def __next__(self):
            return 1

        def close(self):
            raise RuntimeError("CLOSE failed")

    with caplog.at_level("WARNING", logger="streamed_read"):
        with pytest.raises(StreamedReadTimeout):
            list(stream_rows(BadClose(), what="t", timeout_ms=2000))
    assert "closing the aborted read failed" in caplog.text


def test_http_variant_turns_the_timeout_into_a_short_503(clock, caplog):
    events: list[str] = []
    with caplog.at_level("WARNING", logger="streamed_read"):
        with pytest.raises(HTTPException) as exc:
            list(stream_rows_or_503(TrackedRows(100, events), route="GET /api/reliability/multi-channel",
                                    timeout_ms=4000))
    assert exc.value.status_code == 503
    assert exc.value.detail == "DB 조회가 4초 안에 끝나지 않아 중단했습니다. 잠시 후 다시 시도해 주세요."
    assert isinstance(exc.value.__cause__, StreamedReadTimeout)
    assert events == ["closed"]
    assert "GET /api/reliability/multi-channel (elapsed 5.0s, 4 rows)" in caplog.text
    assert list(stream_rows_or_503(range(3), route="GET /x", timeout_ms=60_000)) == [0, 1, 2]


# ───────────────────────────────────────────────────────────────────────
# SQLite 실제 커서 — 멈춘 뒤 DBAPI 커서가 닫혀 있다
# ───────────────────────────────────────────────────────────────────────


def test_abort_closes_the_real_dbapi_cursor_of_a_yield_per_query(clock):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    models.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    cursors: list = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "FROM probe_results" in statement:
            cursors.append(cursor)

    event.listen(engine, "after_cursor_execute", record)
    try:
        with factory() as db:
            db.add_all(models.ProbeResult(run_id=1, model_id=f"m{i}", model_name="M", status="success",
                                          prompt="p") for i in range(50))
            db.commit()
            inner = iter(db.query(models.ProbeResult.model_id).yield_per(4))  # 붙잡아 둔다
            got = []
            with pytest.raises(StreamedReadTimeout):
                for (model_id,) in stream_rows(inner, what="t", timeout_ms=10_000):
                    got.append(model_id)
            assert len(got) == 10 < 50
            (cursor,) = cursors
            with pytest.raises(sqlite3.ProgrammingError, match="closed cursor"):
                cursor.fetchone()
            assert inner.gi_frame is None
            assert db.query(func.count(models.ProbeResult.id)).scalar() == 50  # 세션은 그대로 쓸 수 있다
    finally:
        event.remove(engine, "after_cursor_execute", record)
        engine.dispose()


# ───────────────────────────────────────────────────────────────────────
# PostgreSQL 증명 — statement_timeout은 FETCH 하나에만 걸린다
# ───────────────────────────────────────────────────────────────────────

PG_URL = os.environ.get("TEST_PG_URL")
_ROWS, _SLEEP_S, _BATCH = 60, 0.04, 5  # 행마다 40ms → FETCH 5행 0.2초, 전체 2.4초
_PG_TIMEOUT_MS = 1000


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
def pg_session(pg_url):
    engine = create_engine(pg_url, connect_args={"options": f"-c statement_timeout={_PG_TIMEOUT_MS}",
                                                 "connect_timeout": 3})
    factory = sessionmaker(bind=engine)
    try:
        with factory() as db:
            yield db
    finally:
        engine.dispose()


def _slow_query(db):
    """행마다 pg_sleep을 부르는 ORM 조회 — FETCH가 가져오는 행만큼만 잔다."""
    i = func.generate_series(1, _ROWS).column_valued("i")
    return db.query(i, func.pg_sleep(_SLEEP_S))


def _open_cursors(db) -> int:
    return db.execute(text("SELECT count(*) FROM pg_cursors")).scalar()


def test_pg_statement_timeout_cancels_a_buffered_read_but_not_a_yield_per_read(pg_session):
    db = pg_session
    started = time.monotonic()
    with pytest.raises(OperationalError, match="statement timeout"):
        _slow_query(db).all()  # 문장 하나 — 1초에서 취소
    assert time.monotonic() - started < 2.0
    db.rollback()

    started = time.monotonic()
    rows = [i for i, _ in _slow_query(db).yield_per(_BATCH)]  # FETCH마다 0.2초 — 끝까지 읽는다
    elapsed = time.monotonic() - started
    assert rows == list(range(1, _ROWS + 1))
    assert elapsed > 2 * _PG_TIMEOUT_MS / 1000  # 전체가 statement_timeout의 두 배를 넘어도 취소되지 않았다


def test_pg_stream_rows_aborts_near_the_limit_and_closes_the_server_side_cursor(pg_session, caplog):
    db = pg_session
    inner = iter(_slow_query(db).yield_per(_BATCH))  # 붙잡아 둔다
    got = []
    started = time.monotonic()
    with caplog.at_level("WARNING", logger="streamed_read"):
        with pytest.raises(StreamedReadTimeout) as exc:
            for i, _ in stream_rows(inner, what="pg proof", timeout_ms=_PG_TIMEOUT_MS):
                assert _open_cursors(db) == 1  # 읽는 동안에는 이름 있는 커서가 열려 있다
                got.append(i)
    elapsed = time.monotonic() - started
    limit_s = _PG_TIMEOUT_MS / 1000
    assert limit_s < exc.value.elapsed_s < limit_s + 2 * _BATCH * _SLEEP_S  # 상한 + FETCH 하나 안쪽
    assert elapsed < limit_s + 0.8 < _ROWS * _SLEEP_S  # 끝까지(2.4초) 읽지 않았다
    assert 0 < len(got) < _ROWS
    assert _open_cursors(db) == 0  # CLOSE됐다 — 커넥션은 트랜잭션 안에서 그대로
    assert db.execute(text("SELECT 1")).scalar() == 1
    assert "pg proof" in caplog.text


# 실제 라우트 — probe_results를 행마다 30ms 자는 뷰로 바꾼 스키마에서 /api/reliability/multi-channel을 부른다.
_E2E_SCHEMA = "streamed_read_e2e"
_E2E_ROWS, _E2E_SLEEP_S = 80, 0.03  # 끝까지 2.4초


@pytest.fixture()
def pg_slow_reliability(pg_url, monkeypatch):
    admin = create_engine(pg_url)
    with admin.begin() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {_E2E_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {_E2E_SCHEMA}"))
    engine = create_engine(pg_url, connect_args={
        "options": f"-c statement_timeout={_PG_TIMEOUT_MS} -c search_path={_E2E_SCHEMA}", "connect_timeout": 3})
    try:
        models.Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            db.add(models.ProbeRun(id=1, prompt="auto", status="completed", is_auto=1))
            now = datetime.now(timezone.utc)
            db.add_all(models.ProbeResult(run_id=1, model_id="global.anthropic.claude-sonnet-5",
                                          model_name="Bedrock Claude Sonnet 5 (Global)", timestamp=now,
                                          prompt="p", status="success", ttft_ms=500.0, total_latency_ms=1500.0,
                                          tps=40.0) for _ in range(_E2E_ROWS))
            db.commit()
        with engine.begin() as conn:
            conn.execute(text("CREATE FUNCTION slow_true() RETURNS boolean LANGUAGE plpgsql VOLATILE AS "
                              f"$$ BEGIN PERFORM pg_sleep({_E2E_SLEEP_S}); RETURN true; END $$"))
            conn.execute(text("ALTER TABLE probe_results RENAME TO probe_results_base"))
            conn.execute(text("CREATE VIEW probe_results AS SELECT * FROM probe_results_base WHERE slow_true()"))

        app = FastAPI()
        app.include_router(reliability_router.router)

        def db_override():
            with factory() as db:
                yield db

        app.dependency_overrides[database.get_db] = db_override
        monkeypatch.setattr(reliability_router, "_YIELD_PER", 5)  # FETCH 5행 = 0.15초 < statement_timeout 1초
        monkeypatch.setattr(database, "_STATEMENT_TIMEOUT_MS", _PG_TIMEOUT_MS)  # 엔진의 statement_timeout과 같은 값
        with TestClient(app) as client:
            yield client, engine
    finally:
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {_E2E_SCHEMA} CASCADE"))
        admin.dispose()


def test_pg_reliability_route_answers_503_near_the_limit_and_returns_its_connection(pg_slow_reliability, monkeypatch,
                                                                                    caplog):
    client, engine = pg_slow_reliability
    url = "/api/reliability/multi-channel?window=1h"
    started = time.monotonic()
    with caplog.at_level("WARNING", logger="streamed_read"):
        resp = client.get(url)
    elapsed = time.monotonic() - started
    assert resp.status_code == 503
    assert resp.json() == {"detail": "DB 조회가 1초 안에 끝나지 않아 중단했습니다. 잠시 후 다시 시도해 주세요."}
    assert elapsed < 1.8 < _E2E_ROWS * _E2E_SLEEP_S
    assert "GET /api/reliability/multi-channel window='1h'" in caplog.text
    assert engine.pool.checkedout() == 0  # 커넥션이 풀로 돌아왔다

    # 상한을 끄면(0) 같은 라우트가 statement_timeout 1초 아래에서 2.4초 동안 끝까지 읽는다 — FETCH마다 따로 걸린다.
    monkeypatch.setattr(database, "_STATEMENT_TIMEOUT_MS", 0)
    started = time.monotonic()
    resp = client.get(url)
    assert resp.status_code == 200
    assert time.monotonic() - started > 2 * _PG_TIMEOUT_MS / 1000
    (family,) = resp.json()["families"]
    assert family["channels"][0]["samples"] == _E2E_ROWS
