"""lifespan 마이그레이션 블록의 기동 비용 가드 (2026-09-06 v2.23.1 롤아웃 롤백 실사고).

배경: 매 기동마다 실행되는 라벨 rename/삭제 문장이 probe_results 전수 스캔을 타 ~130s가 걸려
ALB 헬스체크 유예를 넘겼고, 대기열에 선 ALTER TABLE이 읽기까지 막았다. 실제 PG 없이
소스 수준으로 세 가지 방어선을 고정한다: (1) lock_timeout, (2) model_name 인덱스 선언,
(3) 인덱스 빌드가 기동 경로를 막지 않도록 백그라운드 스레드에서 실행.
"""
import pathlib
import re

import models

MAIN_SRC = (pathlib.Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")


def test_migration_block_sets_lock_timeout_before_advisory_lock():
    st = MAIN_SRC.index("SET statement_timeout = '30000'")
    lt = MAIN_SRC.index("SET lock_timeout = '5000'")
    adv = MAIN_SRC.index("SELECT pg_advisory_lock(917350001)")
    assert st < lt < adv, "lock_timeout must be set right after statement_timeout and before the advisory lock"


def test_probe_results_declares_model_name_index():
    names = {idx.name for idx in models.ProbeResult.__table__.indexes}
    assert "ix_probe_results_model_name" in names
    assert any(idx.name == "ix_probe_results_model_name" for idx in models._PERF_INDEXES)


def test_performance_indexes_run_in_background_thread():
    assert re.search(r"threading\.Thread\([^)]*name=\"perf-indexes\"[^)]*daemon=True", MAIN_SRC), (
        "ensure_performance_indexes must run in a daemon thread so /api/health opens before index builds finish"
    )
    # 기동 경로(동기)에서는 더 이상 직접 호출하지 않는다.
    sync_calls = [m.start() for m in re.finditer(r"^\s{4}ensure_performance_indexes\(engine\)", MAIN_SRC, re.M)]
    assert sync_calls == []
