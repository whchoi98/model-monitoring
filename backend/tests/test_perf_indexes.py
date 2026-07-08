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
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    with engine.begin() as conn:
        models.ensure_performance_indexes(conn)
        models.ensure_performance_indexes(conn)
    names = {i["name"] for i in inspect(engine).get_indexes("probe_results")}
    assert {"ix_probe_results_run_id", "ix_probe_results_timestamp"} <= names
    run_names = {i["name"] for i in inspect(engine).get_indexes("probe_runs")}
    assert "ix_probe_runs_auto_status_created" in run_names
