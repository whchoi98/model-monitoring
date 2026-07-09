"""Perf regression guard: 대시보드 trend/latest 쿼리가 의존하는 DB 인덱스 정의 고정.

2026-07-08: probe_runs/probe_results에 PK 외 인덱스가 전무해 /api/auto-probe/trend가
hours=1(336행)에도 4초+ 걸렸다 (풀 스캔 × 2 + t4g.micro CPU 크레딧 소진).
cost/reliability/efficiency/analysis 라우터도 전부 probe_results.timestamp 필터를
사용하므로 timestamp 인덱스는 전 페이지 공통 이득.

이 테스트는 (1) 모델 선언에 인덱스가 존재하고 (2) 기존 DB용 마이그레이션 헬퍼가
멱등하게 동작함을 고정한다.
"""

from sqlalchemy import create_engine, inspect

import models


def _index_map(table):
    return {idx.name: [c.name for c in idx.columns] for idx in table.indexes}


def test_probe_runs_composite_index_declared():
    # trend/status/latest 공통: WHERE is_auto=1 AND status='completed' (+ created_at 범위/정렬)
    m = _index_map(models.ProbeRun.__table__)
    assert m.get("ix_probe_runs_auto_status_created") == ["is_auto", "status", "created_at"]


def test_probe_results_run_id_and_timestamp_indexes_declared():
    m = _index_map(models.ProbeResult.__table__)
    assert m.get("ix_probe_results_run_id") == ["run_id"]  # trend JOIN + latest
    assert m.get("ix_probe_results_timestamp") == ["timestamp"]  # cost/reliability/efficiency/analysis


def test_ensure_performance_indexes_is_idempotent():
    # 기존 운영 DB 마이그레이션 경로: create_all이 이미 만든 뒤에도, 두 번 실행해도 에러 없어야 한다.
    # (engine을 받아 자체 커넥션으로 실행 — PG에서는 CONCURRENTLY라 호출측 트랜잭션에 못 들어감.)
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    models.ensure_performance_indexes(engine)
    models.ensure_performance_indexes(engine)
    names = {i["name"] for i in inspect(engine).get_indexes("probe_results")}
    assert {"ix_probe_results_run_id", "ix_probe_results_timestamp"} <= names
    run_names = {i["name"] for i in inspect(engine).get_indexes("probe_runs")}
    assert "ix_probe_runs_auto_status_created" in run_names


def test_ensure_performance_indexes_pg_uses_concurrently_and_long_timeout():
    """운영 PG 경로 회귀 가드 (2026-07-09 실사고).

    lifespan 마이그레이션 트랜잭션(statement_timeout 30s) 안에서 일반 CREATE INDEX를
    실행하면 큰 probe_results에서 타임아웃으로 실패한다. PG에서는 (1) CONCURRENTLY로
    쓰기 블로킹 없이, (2) 10분 타임아웃으로, (3) 자체 AUTOCOMMIT 커넥션에서 실행해야 한다.
    실제 PG 없이 SQL 텍스트를 캡처해 고정한다.
    """
    executed: list[str] = []

    class FakeConn:
        def execution_options(self, **kw):
            assert kw.get("isolation_level") == "AUTOCOMMIT"
            return self

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, stmt, *a, **kw):
            executed.append(str(stmt))

            class R:
                def first(self):
                    return None

            return R()

    class FakeDialect:
        name = "postgresql"

    class FakeEngine:
        dialect = FakeDialect()

        def connect(self):
            return FakeConn()

    models.ensure_performance_indexes(FakeEngine())

    joined = "\n".join(executed)
    assert "statement_timeout = '600000'" in joined
    assert joined.count("CREATE INDEX CONCURRENTLY IF NOT EXISTS") == 3
    assert "ix_probe_runs_auto_status_created ON probe_runs (is_auto, status, created_at)" in joined
    assert "ix_probe_results_run_id ON probe_results (run_id)" in joined
    assert "ix_probe_results_timestamp ON probe_results (timestamp)" in joined
