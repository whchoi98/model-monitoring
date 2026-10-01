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
    """v2.32.2부터 설정 두 개와 advisory 락은 트랜잭션 한정이다 (test_startup_pool_state.py).

    세션 수준 SET은 풀로 돌아간 커넥션에 5초 lock_timeout, 30초 statement_timeout을 남겼고, 세션 락은 블록이 실패하면
    finally의 unlock이 중단된 트랜잭션에서 실패해 그 커넥션에 남아 다음 태스크의 기동을 lock_timeout 뒤 실패시켰다.
    """
    body = MAIN_SRC[MAIN_SRC.index("async def lifespan("):MAIN_SRC.index("\ndef _ensure_price_schema(")]
    st = body.index("SET LOCAL statement_timeout = '30000'")
    lt = body.index("SET LOCAL lock_timeout = '5000'")
    adv = body.index("SELECT pg_advisory_xact_lock(917350001)")
    assert st < lt < adv, "lock_timeout must be set right after statement_timeout and before the advisory lock"
    for session_form in ("SET statement_timeout", "SET lock_timeout", "pg_advisory_lock(", "pg_advisory_unlock("):
        assert session_form not in body, session_form


def test_migration_block_checks_the_catalog_before_adding_columns():
    """열 추가는 advisory 락 다음, 첫 DELETE 앞의 확인 함수만 한다 (2026-09-30 LockNotAvailable, test_startup_column_guard.py).

    lifespan이 ALTER TABLE을 직접 실행하면 열이 이미 있어도 ACCESS EXCLUSIVE를 요청해 읽기 트랜잭션 하나에 5초 막힌다.
    """
    body = MAIN_SRC[MAIN_SRC.index("async def lifespan("):MAIN_SRC.index("\ndef _ensure_price_schema(")]
    adv = body.index("SELECT pg_advisory_xact_lock(917350001)")
    guard = body.index("_add_missing_startup_columns(conn)")
    first_dml = body.index("DELETE FROM probe_results")
    assert adv < guard < first_dml
    assert re.search(r'text\(f?"ALTER TABLE', body) is None


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
