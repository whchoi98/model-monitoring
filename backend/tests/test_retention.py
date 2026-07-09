"""데이터 보존 정책 테스트 — 원본 60일 보존 + 시간 단위 집계 이관 (v2.7.0).

probe_results가 5분마다 28행씩 무한 성장(2026-07-09 기준 22.7만 행)하므로,
보존 기간(기본 60일, RETENTION_DAYS로 조정)을 지난 원본은 probe_results_hourly로
집계 이관 후 삭제한다. 집계+삭제는 한 트랜잭션(원자적) — 중간 실패 시 중복 없이 재시도.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import models
from retention import apply_retention


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    models.Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


NOW = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


def _seed(s, *, days_ago, hour_offset_min=0, ttft=100.0, status="success",
          model="Bedrock Claude Haiku 4.5 (US)", in_tok=10, out_tok=50):
    ts = NOW - timedelta(days=days_ago) + timedelta(minutes=hour_offset_min)
    run = models.ProbeRun(prompt="p", status="completed", is_auto=1, created_at=ts)
    s.add(run)
    s.flush()
    s.add(models.ProbeResult(
        run_id=run.id, model_id="m1", model_name=model, timestamp=ts,
        prompt="p", status=status,
        ttft_ms=ttft if status == "success" else None,
        total_latency_ms=ttft * 2 if status == "success" else None,
        tps=40.0 if status == "success" else None,
        input_tokens=in_tok if status == "success" else None,
        output_tokens=out_tok if status == "success" else None,
        output_text="X" * 100, category="chat-short",
    ))
    s.commit()
    return run.id


def test_old_rows_are_aggregated_hourly_and_deleted(session):
    # 61일 전 같은 시간대 버킷: 성공 2건(ttft 100/300) + 에러 1건
    _seed(session, days_ago=61, hour_offset_min=0, ttft=100.0)
    _seed(session, days_ago=61, hour_offset_min=5, ttft=300.0)
    _seed(session, days_ago=61, hour_offset_min=10, status="error")
    # 보존 기간 안(1일 전) — 건드리면 안 됨
    keep_run = _seed(session, days_ago=1, ttft=999.0)

    stats = apply_retention(session, retention_days=60, now=NOW)

    hourly = session.query(models.ProbeResultHourly).all()
    assert len(hourly) == 1
    b = hourly[0]
    assert b.cnt == 3
    assert b.success_cnt == 2
    assert b.avg_ttft_ms == 200.0  # (100+300)/2 — 에러(null)는 평균 제외
    assert b.avg_total_latency_ms == 400.0
    assert b.sum_input_tokens == 20
    assert b.sum_output_tokens == 100
    assert b.model_name == "Bedrock Claude Haiku 4.5 (US)"
    assert b.category == "chat-short"

    # 원본: 옛 3건 삭제, 최근 1건 유지
    remaining = session.query(models.ProbeResult).all()
    assert len(remaining) == 1
    assert remaining[0].ttft_ms == 999.0
    # 결과가 사라진 옛 run도 삭제, 최근 run 유지
    runs = session.query(models.ProbeRun).all()
    assert [r.id for r in runs] == [keep_run]

    assert stats["deleted_results"] == 3
    assert stats["aggregated_buckets"] == 1


def test_model_and_bucket_split(session):
    # 같은 시각, 다른 모델 → 버킷 분리
    _seed(session, days_ago=61, model="Model A", ttft=100.0)
    _seed(session, days_ago=61, model="Model B", ttft=200.0)
    # 같은 모델, 다른 시간대 → 버킷 분리
    _seed(session, days_ago=61, hour_offset_min=90, model="Model A", ttft=300.0)

    apply_retention(session, retention_days=60, now=NOW)

    hourly = session.query(models.ProbeResultHourly).all()
    assert len(hourly) == 3


def test_second_run_is_noop(session):
    _seed(session, days_ago=61)
    apply_retention(session, retention_days=60, now=NOW)
    stats2 = apply_retention(session, retention_days=60, now=NOW)

    assert stats2["deleted_results"] == 0
    assert stats2["aggregated_buckets"] == 0
    assert session.query(models.ProbeResultHourly).count() == 1  # 중복 집계 없음


def test_disabled_when_days_nonpositive(session):
    _seed(session, days_ago=61)
    stats = apply_retention(session, retention_days=0, now=NOW)
    assert stats["deleted_results"] == 0
    assert session.query(models.ProbeResult).count() == 1  # 아무것도 삭제 안 됨


def test_default_days_from_env(session, monkeypatch):
    monkeypatch.setenv("RETENTION_DAYS", "30")
    _seed(session, days_ago=31)   # 30일 정책이면 삭제 대상
    _seed(session, days_ago=29)   # 유지
    stats = apply_retention(session, now=NOW)
    assert stats["deleted_results"] == 1
    assert session.query(models.ProbeResult).count() == 1
